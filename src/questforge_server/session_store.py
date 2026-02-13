# src/questforge_server/session_store.py
from __future__ import annotations

import json
import os
import time
import uuid
import traceback
import threading
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

from questforge.core.models import DetectiveState, GameConfig
from questforge.engine.case_selector import CaseSelector
from questforge.engine.session import GameSession
from questforge.content.cases import CASES

from questforge.ai.runtime_story_nodes_generator_v1 import RuntimeStoryNodesGeneratorV1
from questforge.adapters.story_nodes_to_session import build_game_session_from_story_nodes
from questforge.contracts.story_nodes_v1 import story_nodes_package_from_dict


def _env_bool(name: str, default: bool = False) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    v = (os.getenv(name) or "").strip()
    if not v:
        return int(default)
    try:
        return int(v)
    except Exception:
        return int(default)


def _attach_case_id(sess: GameSession, case_id: str) -> None:
    """
    ✅ 讓 routes_game 可以用 session.case_id 判斷（例如 QF_TTS_ONLY_AI）
    """
    try:
        setattr(sess, "case_id", (case_id or "").strip())
    except Exception:
        pass


def _set_story_meta(
    sess: GameSession,
    *,
    source: str,
    status: str,
    stage: str = "",
    error: str = "",
    forced_case_id: str = "",
) -> None:
    """
    把 AI/Static/Pool 狀態塞到 session.state.vars，routes_game 會打進 view.runtime.story
    """
    try:
        if not hasattr(sess, "state") or sess.state is None:
            return
        vars_ = getattr(sess.state, "vars", None)
        if vars_ is None:
            return
        vars_["qf_story"] = {
            "source": source,        # "ai" | "static" | "pool"
            "status": status,        # "ok" | "generating" | "failed"
            "stage": stage,          # bootstrap_current_tts / bootstrap_ai1 / ...
            "error": error or "",
            "forced_case_id": forced_case_id or "",
        }
    except Exception:
        return


@dataclass
class _StorySlot:
    sess: GameSession
    case_id: str
    run_id: str
    prefetched_bundle: Optional[Dict[str, Any]] = None


@dataclass
class _StoreItem:
    ts: float
    current: _StorySlot
    next1: _StorySlot
    next2: _StorySlot

    # ✅ 每個 sid 一條背景隊列，保證順序（current_tts -> ai1 -> ai2）
    bg_lock: threading.Lock
    bg_running: bool = False


# ============================================================
# Utilities: AI failure dump
# ============================================================

def _ensure_cache_dir() -> Path:
    root = Path(".qf_cache/generated_stories").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _dump_ai_failure(
    *,
    stage: str,
    sid: str,
    seed: Optional[int],
    err: BaseException,
    tb: str,
) -> None:
    try:
        root = _ensure_cache_dir()
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        sid6 = (sid or "")[:6]

        meta = {
            "ts": ts,
            "stage": stage,
            "sid": sid,
            "sid6": sid6,
            "seed": seed,
            "error_type": type(err).__name__,
            "error": str(err),
        }

        (root / "last_failed_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        lines: list[str] = []
        lines.append(f"ts: {ts}")
        lines.append(f"stage: {stage}")
        lines.append(f"sid: {sid} (sid6={sid6})")
        lines.append(f"seed: {seed}")
        lines.append("")
        lines.append(f"error: {type(err).__name__}: {err}")
        lines.append("")
        lines.append("traceback:")
        lines.append(tb.rstrip())
        lines.append("")

        (root / "last_failed.txt").write_text("\n".join(lines), encoding="utf-8")
        print(f"[AI_FAIL_DUMP] saved: {root / 'last_failed.txt'}", flush=True)
    except Exception as e:
        print(f"[AI_FAIL_DUMP] fail: {e!r}", flush=True)


# ============================================================
# Pool loader
# ============================================================

def _pool_dir() -> Path:
    d = (os.getenv("QF_POOL_DIR") or ".qf_cache/pool").strip()
    return Path(d).resolve()


def _list_pool_files() -> List[Path]:
    root = _pool_dir()
    if not root.exists():
        return []
    files = [p for p in root.glob("*.json") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _pick_pool_file(seed: Optional[int] = None) -> Optional[Path]:
    files = _list_pool_files()
    if not files:
        return None
    if seed is None:
        idx = int(time.time()) % len(files)
        return files[idx]
    return files[int(seed) % len(files)]


# ============================================================
# SessionStore
# ============================================================

class SessionStore:
    def __init__(self, ttl_seconds: int = 60 * 60) -> None:
        self.ttl_seconds = int(ttl_seconds or 0) or (60 * 60)
        self._items: Dict[str, _StoreItem] = {}
        self._gen = RuntimeStoryNodesGeneratorV1()

        self._ai_enabled = _env_bool("QF_AI_STORY_ENABLED", True)
        # 目前這個 flag 先留著（你這版流程以 pool 為 current，比較不需要 fallback）
        self._ai_fallback_to_static = _env_bool("QF_AI_FALLBACK_TO_STATIC", False)

        # 先保留，未來如果你想改成 N 個 AI 預生，可以用它
        self._bootstrap_ai_count = max(0, _env_int("QF_BOOTSTRAP_AI_COUNT", 2))

    def _cleanup(self) -> None:
        now = time.time()
        expired = []
        for sid, item in self._items.items():
            if now - item.ts > self.ttl_seconds:
                expired.append(sid)
        for sid in expired:
            self._items.pop(sid, None)

    # ----------------------------
    # getters
    # ----------------------------
    def get(self, session_id: str) -> Optional[GameSession]:
        self._cleanup()
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        if not item:
            return None
        item.ts = time.time()
        return item.current.sess

    def get_case_id(self, session_id: str) -> Optional[str]:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        return item.current.case_id if item else None

    def get_current_run_id(self, session_id: str) -> Optional[str]:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        return item.current.run_id if item else None

    def get_next1(self, session_id: str) -> Optional[GameSession]:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        if not item:
            return None
        item.ts = time.time()
        return item.next1.sess

    def get_next2(self, session_id: str) -> Optional[GameSession]:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        if not item:
            return None
        item.ts = time.time()
        return item.next2.sess

    def get_next1_run_id(self, session_id: str) -> Optional[str]:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        return item.next1.run_id if item else None

    def get_next2_run_id(self, session_id: str) -> Optional[str]:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        return item.next2.run_id if item else None

    def get_next1_prefetched_bundle(self, session_id: str) -> Optional[Dict[str, Any]]:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        return item.next1.prefetched_bundle if item else None

    def set_next1_prefetched_bundle(self, session_id: str, bundle: Optional[Dict[str, Any]]) -> None:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        if not item:
            return
        item.next1.prefetched_bundle = bundle
        item.ts = time.time()

    def get_next2_prefetched_bundle(self, session_id: str) -> Optional[Dict[str, Any]]:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        return item.next2.prefetched_bundle if item else None

    def set_next2_prefetched_bundle(self, session_id: str, bundle: Optional[Dict[str, Any]]) -> None:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        if not item:
            return
        item.next2.prefetched_bundle = bundle
        item.ts = time.time()

    def delete(self, session_id: str) -> None:
        sid = (session_id or "").strip()
        if not sid:
            return
        self._items.pop(sid, None)

    # ----------------------------
    # Static CASES builder
    # ----------------------------
    def _build_session_from_cases(self, case_id: str, seed: int | None = None) -> Tuple[str, GameSession]:
        case = CASES.get(case_id)
        if not case:
            selector = CaseSelector(CASES)
            case_id, case = selector.pick()

        nodes = case.get("nodes") or {}
        start_node = (
            (case.get("start_node") or "").strip()
            or (case.get("start") or "").strip()
            or next(iter(nodes.keys()))
        )
        solve_rule = case.get("solve_rule") or {}

        config_kwargs: Dict[str, Any] = {}
        try:
            cfg_fields = {f.name for f in fields(GameConfig)}
            if seed is not None and "seed" in cfg_fields:
                config_kwargs["seed"] = int(seed)
        except Exception:
            pass

        config = GameConfig(**config_kwargs)  # type: ignore[arg-type]
        state = DetectiveState()
        sess = GameSession(
            state=state,
            nodes=nodes,
            start_node=start_node,
            config=config,
            solve_rule=solve_rule,
        )
        _attach_case_id(sess, case_id)
        return case_id, sess

    def _pick_static_case_id(self, exclude: Optional[str] = None) -> str:
        selector = CaseSelector(CASES)
        cid, _ = selector.pick()
        if exclude and cid == exclude:
            all_ids = list(CASES.keys())
            candidates = [x for x in all_ids if x != exclude]
            if candidates:
                cid = candidates[int(time.time()) % len(candidates)]
        return cid

    # ----------------------------
    # Pool builder (StoryNodesPackage JSON)
    # ----------------------------
    def _build_session_from_pool(self, *, seed: int | None = None, stage: str) -> Tuple[str, GameSession, str]:
        """
        return: (case_id, session, filename)
        """
        p = _pick_pool_file(seed=seed)
        if p is None:
            raise RuntimeError("pool_empty")

        raw = json.loads(p.read_text(encoding="utf-8"))
        pkg = story_nodes_package_from_dict(raw)
        sess, _solve_rule = build_game_session_from_story_nodes(pkg=pkg, seed=seed)
        case_id = (pkg.meta.case_id or "").strip() or f"pool_{p.stem}"

        _attach_case_id(sess, case_id)
        _set_story_meta(sess, source="pool", status="ok", stage=stage, forced_case_id=case_id)
        return case_id, sess, p.name

    # ----------------------------
    # AI builder
    # ----------------------------
    def _build_ai_session(
        self,
        *,
        sid: str,
        seed: int | None,
        stage: str,
        forced_case_id: str,
    ) -> tuple[str, GameSession]:
        sid6 = (sid or "")[:6]
        try:
            print(f"[AI_BUILD] stage={stage} sid={sid6} seed={seed} forced_case_id={forced_case_id}", flush=True)
            pkg = self._gen.generate(seed=seed, forced_case_id=forced_case_id)
            sess, _solve_rule = build_game_session_from_story_nodes(pkg=pkg, seed=seed)
            case_id = (pkg.meta.case_id or "").strip() or forced_case_id

            _attach_case_id(sess, case_id)
            _set_story_meta(sess, source="ai", status="ok", stage=stage, forced_case_id=forced_case_id)
            print(f"[AI_BUILD] ok stage={stage} sid={sid6} case_id={case_id}", flush=True)
            return case_id, sess
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[AI_BUILD] fail stage={stage} sid={sid6} err={e!r}", flush=True)
            print(tb, flush=True)
            _dump_ai_failure(stage=stage, sid=sid, seed=seed, err=e, tb=tb)
            raise

    # ----------------------------
    # Public: create + rotate
    # ----------------------------
    def create(self, seed: int | None = None) -> Tuple[str, GameSession]:
        """
        你的流程：
        - current：pool（若 pool 空就 static）=> 立刻可玩
        - next1/next2：static placeholder（立刻有東西），背景會依序換成 AI（routes 做 tts prewarm / prefetch）
        """
        self._cleanup()
        sid = uuid.uuid4().hex
        sid6 = sid[:6]

        # current: pool first
        try:
            case_a, sess_a, fname = self._build_session_from_pool(seed=seed, stage="create_current_pool")
            print(f"[START] sid={sid6} current=POOL file={fname} case_id={case_a}", flush=True)
        except Exception as e:
            case_a = self._pick_static_case_id()
            case_a, sess_a = self._build_session_from_cases(case_id=case_a, seed=seed)
            _set_story_meta(sess_a, source="static", status="ok", stage="create_current_static", error=repr(e))
            print(f"[START] sid={sid6} current=STATIC case_id={case_a} (pool_fail={e!r})", flush=True)

        # next placeholders (static)
        case_b = self._pick_static_case_id(exclude=case_a)
        case_b, sess_b = self._build_session_from_cases(case_id=case_b, seed=seed)
        _set_story_meta(
            sess_b,
            source="static",
            status="generating" if self._ai_enabled else "ok",
            stage="create_next1_placeholder",
        )

        case_c = self._pick_static_case_id(exclude=case_b)
        case_c, sess_c = self._build_session_from_cases(case_id=case_c, seed=seed)
        _set_story_meta(
            sess_c,
            source="static",
            status="generating" if self._ai_enabled else "ok",
            stage="create_next2_placeholder",
        )

        item = _StoreItem(
            ts=time.time(),
            current=_StorySlot(sess=sess_a, case_id=case_a, run_id=uuid.uuid4().hex, prefetched_bundle=None),
            next1=_StorySlot(sess=sess_b, case_id=case_b, run_id=uuid.uuid4().hex, prefetched_bundle=None),
            next2=_StorySlot(sess=sess_c, case_id=case_c, run_id=uuid.uuid4().hex, prefetched_bundle=None),
            bg_lock=threading.Lock(),
            bg_running=False,
        )
        self._items[sid] = item
        return sid, sess_a

    def rotate_to_next1(self, session_id: str, seed: int | None = None) -> Tuple[Optional[GameSession], Optional[str]]:
        """
        switch_case 使用：
        - old current run_id 交給 routes 去刪音檔
        - current <- next1, next1 <- next2, next2 <- 新 placeholder（static）
        """
        sid = (session_id or "").strip()
        if not sid:
            return None, None
        self._cleanup()
        item = self._items.get(sid)
        if not item:
            return None, None

        old_run = item.current.run_id
        cur_case = item.current.case_id

        # promote
        item.current = item.next1
        item.next1 = item.next2

        # new next2 placeholder
        new_case = self._pick_static_case_id(exclude=item.next1.case_id)
        new_case, new_sess = self._build_session_from_cases(case_id=new_case, seed=seed)
        _set_story_meta(
            new_sess,
            source="static",
            status="generating" if self._ai_enabled else "ok",
            stage="rotate_next2_placeholder",
        )
        item.next2 = _StorySlot(sess=new_sess, case_id=new_case, run_id=uuid.uuid4().hex, prefetched_bundle=None)
        item.ts = time.time()

        sid6 = sid[:6]
        print(
            f"[ROTATE] sid={sid6} old_current={cur_case} -> current={item.current.case_id} next1={item.next1.case_id} next2(placeholder)={item.next2.case_id}",
            flush=True,
        )
        return item.current.sess, old_run

    # ----------------------------
    # Background queue coordination
    # ----------------------------
    def try_mark_bg_running(self, session_id: str) -> bool:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        if not item:
            return False
        with item.bg_lock:
            if item.bg_running:
                return False
            item.bg_running = True
            return True

    def mark_bg_done(self, session_id: str) -> None:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        if not item:
            return
        with item.bg_lock:
            item.bg_running = False
            item.ts = time.time()

    # ----------------------------
    # Background tasks called by routes
    # ----------------------------
    def build_ai_into_next1(self, *, session_id: str, seed: int | None, stage: str) -> bool:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        if not item:
            return False
        if not self._ai_enabled:
            return False

        sid6 = sid[:6]
        token_run = item.next1.run_id
        try:
            forced_case_id = f"ai_{sid6}_{stage}_{int(time.time())}"
            case_id, sess = self._build_ai_session(sid=sid, seed=seed, stage=stage, forced_case_id=forced_case_id)

            if item.next1.run_id != token_run:
                print(f"[AI_BG] sid={sid6} next1 token changed; drop", flush=True)
                return False

            item.next1 = _StorySlot(sess=sess, case_id=case_id, run_id=token_run, prefetched_bundle=None)
            item.ts = time.time()
            return True
        except Exception as e:
            _set_story_meta(item.next1.sess, source="static", status="failed", stage=stage, error=repr(e))
            print(f"[AI_BG] sid={sid6} build next1 fail stage={stage} err={e!r}", flush=True)
            return False

    def build_ai_into_next2(self, *, session_id: str, seed: int | None, stage: str) -> bool:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        if not item:
            return False
        if not self._ai_enabled:
            return False

        sid6 = sid[:6]
        token_run = item.next2.run_id
        try:
            forced_case_id = f"ai_{sid6}_{stage}_{int(time.time())}"
            case_id, sess = self._build_ai_session(sid=sid, seed=seed, stage=stage, forced_case_id=forced_case_id)

            if item.next2.run_id != token_run:
                print(f"[AI_BG] sid={sid6} next2 token changed; drop", flush=True)
                return False

            item.next2 = _StorySlot(sess=sess, case_id=case_id, run_id=token_run, prefetched_bundle=None)
            item.ts = time.time()
            return True
        except Exception as e:
            _set_story_meta(item.next2.sess, source="static", status="failed", stage=stage, error=repr(e))
            print(f"[AI_BG] sid={sid6} build next2 fail stage={stage} err={e!r}", flush=True)
            return False
