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
from typing import Any, Dict, Optional, Tuple

from questforge.core.models import DetectiveState, GameConfig
from questforge.engine.case_selector import CaseSelector
from questforge.engine.session import GameSession
from questforge.content.cases import CASES

from questforge.ai.runtime_story_nodes_generator_v1 import RuntimeStoryNodesGeneratorV1
from questforge.adapters.story_nodes_to_session import build_game_session_from_story_nodes


def _env_bool(name: str, default: bool = False) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "y", "on")


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
    把 AI/Static 狀態塞到 session.state.vars，給 routes_game 打進 view_json 用。
    """
    try:
        if not hasattr(sess, "state") or sess.state is None:
            return
        vars_ = getattr(sess.state, "vars", None)
        if vars_ is None:
            return
        vars_["qf_story"] = {
            "source": source,        # "ai" | "static"
            "status": status,        # "ok" | "generating" | "failed"
            "stage": stage,          # create_current / create_next_bg / swap_next_bg ...
            "error": error or "",
            "forced_case_id": forced_case_id or "",
        }
    except Exception:
        return


# ============================================================
# Internal models
# ============================================================

@dataclass
class _StoreItem:
    ts: float
    current: GameSession
    current_case_id: str
    next: GameSession
    next_case_id: str

    # ✅ 每個 case-run 一個 run_id（用來隔離/刪除語音包）
    current_run_id: str
    next_run_id: str

    # ✅ next 的「第一頁 bundle」預生成快取（raw dict）
    next_prefetched_bundle: Optional[Dict[str, Any]] = None


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
# SessionStore
# ============================================================

class SessionStore:
    def __init__(self, ttl_seconds: int = 60 * 60) -> None:
        self.ttl_seconds = int(ttl_seconds or 0) or (60 * 60)
        self._items: Dict[str, _StoreItem] = {}
        self._gen = RuntimeStoryNodesGeneratorV1()

        # ✅ 開關：AI 生成是否啟用、失敗是否 fallback 靜態
        self._ai_enabled = _env_bool("QF_AI_STORY_ENABLED", True)
        self._ai_fallback_to_static = _env_bool("QF_AI_FALLBACK_TO_STATIC", False)

    def _cleanup(self) -> None:
        now = time.time()
        expired = []
        for sid, item in self._items.items():
            if now - item.ts > self.ttl_seconds:
                expired.append(sid)
        for sid in expired:
            self._items.pop(sid, None)

    def get(self, session_id: str) -> Optional[GameSession]:
        self._cleanup()
        sid = (session_id or "").strip()
        if not sid:
            return None
        item = self._items.get(sid)
        if not item:
            return None
        item.ts = time.time()
        return item.current

    def get_next(self, session_id: str) -> Optional[GameSession]:
        self._cleanup()
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        if not item:
            return None
        item.ts = time.time()
        return item.next

    def get_case_id(self, session_id: str) -> Optional[str]:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        if not item:
            return None
        return item.current_case_id

    # ----------------------------
    # run_id / prefetch cache
    # ----------------------------
    def get_current_run_id(self, session_id: str) -> Optional[str]:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        return item.current_run_id if item else None

    def get_next_run_id(self, session_id: str) -> Optional[str]:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        return item.next_run_id if item else None

    def get_next_prefetched_bundle(self, session_id: str) -> Optional[Dict[str, Any]]:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        return item.next_prefetched_bundle if item else None

    def set_next_prefetched_bundle(self, session_id: str, bundle: Optional[Dict[str, Any]]) -> None:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        if not item:
            return
        item.next_prefetched_bundle = bundle
        item.ts = time.time()

    def delete(self, session_id: str) -> None:
        sid = (session_id or "").strip()
        if not sid:
            return
        self._items.pop(sid, None)

    # ----------------------------
    # Static CASES builder (fallback)
    # ----------------------------
    def _build_session(self, case_id: str, seed: int | None = None) -> Tuple[str, GameSession]:
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
        return case_id, sess

    def _pick_two_cases(self) -> Tuple[str, str]:
        selector = CaseSelector(CASES)
        a, _ = selector.pick()
        b, _ = selector.pick()
        if b == a:
            all_ids = list(CASES.keys())
            candidates = [x for x in all_ids if x != a]
            if candidates:
                b = candidates[int(time.time()) % len(candidates)]
        return a, b

    # ----------------------------
    # AI builder: runtime story_nodes v1
    # ----------------------------
    def _build_ai_session(
        self,
        *,
        sid: str,
        seed: int | None = None,
        stage: str,
        forced_case_id: str,
    ) -> tuple[str, GameSession]:
        sid6 = (sid or "")[:6]
        try:
            print(
                f"[AI_BUILD] stage={stage} sid={sid6} seed={seed} forced_case_id={forced_case_id}",
                flush=True,
            )
            pkg = self._gen.generate(seed=seed, forced_case_id=forced_case_id)
            sess, _solve_rule = build_game_session_from_story_nodes(pkg=pkg, seed=seed)

            case_id = (pkg.meta.case_id or "").strip() or forced_case_id
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
    # Background jobs
    # ----------------------------
    def _spawn_build_next_in_background(
        self,
        *,
        sid: str,
        seed: int | None,
        stage: str,
        token_run_id: str,
    ) -> None:
        sid6 = (sid or "")[:6]

        def _job() -> None:
            if not self._ai_enabled:
                return
            try:
                forced_case_id = f"ai_{sid6}_{stage}_{int(time.time())}"
                new_case, new_sess = self._build_ai_session(
                    sid=sid,
                    seed=seed,
                    stage=stage,
                    forced_case_id=forced_case_id,
                )

                item = self._items.get(sid)
                if not item:
                    print(f"[AI_BG] sid={sid6} item missing; drop result", flush=True)
                    return
                if item.next_run_id != token_run_id:
                    print(f"[AI_BG] sid={sid6} token changed; drop result", flush=True)
                    return

                item.next = new_sess
                item.next_case_id = new_case
                item.next_prefetched_bundle = None
                item.ts = time.time()
                print(f"[AI_BG] sid={sid6} next ready case_id={new_case}", flush=True)

            except Exception as e:
                # ✅ 背景失敗：保留 placeholder，但把 next 標記 failed，UI 可顯示「AI 失敗，先用範例」
                item = self._items.get(sid)
                if item and item.next:
                    _set_story_meta(
                        item.next,
                        source="static",
                        status="failed",
                        stage=stage,
                        error=repr(e),
                    )
                print(f"[AI_BG] sid={sid6} fail stage={stage} err={e!r}", flush=True)

        t = threading.Thread(target=_job, name=f"qf_ai_next_{sid6}", daemon=True)
        t.start()

    # ----------------------------
    # Public: create/reset/swap
    # ----------------------------
    def create(self, seed: int | None = None) -> Tuple[str, GameSession]:
        """
        - current：同步 AI（馬上進遊戲要能玩）
        - next：先放靜態 CASES（立即有 next），並在背景生成 AI next 覆蓋掉
        """
        self._cleanup()
        sid = uuid.uuid4().hex
        sid6 = sid[:6]
        t0 = time.time()
        print(f"[START] sid={sid6} +0.00s create_session:begin seed={seed}", flush=True)

        # A: current
        case_a: str
        sess_a: GameSession

        if self._ai_enabled:
            try:
                forced_case_id = f"ai_{sid6}_create_current_{int(time.time())}"
                case_a, sess_a = self._build_ai_session(
                    sid=sid,
                    seed=seed,
                    stage="create_current",
                    forced_case_id=forced_case_id,
                )
            except Exception as e:
                if not self._ai_fallback_to_static:
                    raise
                print(f"[AI] create_current fallback sid={sid6}: {e!r}", flush=True)
                case_a, _ = self._pick_two_cases()
                case_a, sess_a = self._build_session(case_id=case_a, seed=seed)
                _set_story_meta(sess_a, source="static", status="failed", stage="create_current", error=repr(e))
        else:
            case_a, _ = self._pick_two_cases()
            case_a, sess_a = self._build_session(case_id=case_a, seed=seed)
            _set_story_meta(sess_a, source="static", status="ok", stage="create_current")

        # B: next placeholder（先用靜態）
        case_b, _ = self._pick_two_cases()
        if case_b == case_a:
            case_b, _ = self._pick_two_cases()
        case_b, sess_b = self._build_session(case_id=case_b, seed=seed)

        # ✅ next 一開始標記 generating（代表：目前是範例，但背景會換成 AI）
        if self._ai_enabled:
            _set_story_meta(sess_b, source="static", status="generating", stage="create_next_bg")
        else:
            _set_story_meta(sess_b, source="static", status="ok", stage="create_next_bg")

        next_run_id = uuid.uuid4().hex
        item = _StoreItem(
            ts=time.time(),
            current=sess_a,
            current_case_id=case_a,
            next=sess_b,
            next_case_id=case_b,
            current_run_id=uuid.uuid4().hex,
            next_run_id=next_run_id,
            next_prefetched_bundle=None,
        )
        self._items[sid] = item

        # ✅ 背景生成 next AI（不阻塞）
        self._spawn_build_next_in_background(
            sid=sid,
            seed=seed,
            stage="create_next_bg",
            token_run_id=next_run_id,
        )

        dt = time.time() - t0
        print(
            f"[START] sid={sid6} +{dt:.2f}s create_session:ok current={case_a} next(placeholder)={case_b}",
            flush=True,
        )
        return sid, sess_a

    def reset_current(
        self,
        session_id: str,
        case_id: str,
        seed: int | None = None,
    ) -> Tuple[Optional[GameSession], Optional[str]]:
        sid = (session_id or "").strip()
        if not sid:
            return None, None
        self._cleanup()
        item = self._items.get(sid)
        if not item:
            return None, None

        sid6 = sid[:6]
        old_run = item.current_run_id

        if self._ai_enabled:
            try:
                forced_case_id = f"ai_{sid6}_reset_current_{int(time.time())}"
                new_case_id, sess = self._build_ai_session(
                    sid=sid,
                    seed=seed,
                    stage="reset_current",
                    forced_case_id=forced_case_id,
                )
            except Exception as e:
                if not self._ai_fallback_to_static:
                    raise
                print(f"[AI] reset_current fallback sid={sid6}: {e!r}", flush=True)
                new_case_id, sess = self._build_session(case_id=case_id, seed=seed)
                _set_story_meta(sess, source="static", status="failed", stage="reset_current", error=repr(e))
        else:
            new_case_id, sess = self._build_session(case_id=case_id, seed=seed)
            _set_story_meta(sess, source="static", status="ok", stage="reset_current")

        item.current = sess
        item.current_case_id = new_case_id
        item.current_run_id = uuid.uuid4().hex
        item.ts = time.time()
        return sess, old_run

    def reset(
        self,
        session_id: str,
        case_id: str,
        seed: int | None = None,
    ) -> Tuple[Optional[GameSession], Optional[str]]:
        return self.reset_current(session_id=session_id, case_id=case_id, seed=seed)

    def swap_to_next_and_prefetch(
        self,
        session_id: str,
        seed: int | None = None,
    ) -> Tuple[Optional[GameSession], Optional[str]]:
        sid = (session_id or "").strip()
        if not sid:
            return None, None
        self._cleanup()
        item = self._items.get(sid)
        if not item:
            return None, None

        sid6 = sid[:6]
        old_run = item.current_run_id

        # promote B -> current
        item.current = item.next
        item.current_case_id = item.next_case_id
        item.current_run_id = item.next_run_id

        # new next placeholder（靜態）
        selector = CaseSelector(CASES)
        new_case, _ = selector.pick()
        if new_case == item.current_case_id:
            all_ids = list(CASES.keys())
            candidates = [x for x in all_ids if x != item.current_case_id]
            if candidates:
                new_case = candidates[int(time.time()) % len(candidates)]
        new_case, new_sess = self._build_session(case_id=new_case, seed=seed)

        if self._ai_enabled:
            _set_story_meta(new_sess, source="static", status="generating", stage="swap_next_bg")
        else:
            _set_story_meta(new_sess, source="static", status="ok", stage="swap_next_bg")

        new_next_run_id = uuid.uuid4().hex
        item.next = new_sess
        item.next_case_id = new_case
        item.next_run_id = new_next_run_id
        item.next_prefetched_bundle = None
        item.ts = time.time()

        # background overwrite
        self._spawn_build_next_in_background(
            sid=sid,
            seed=seed,
            stage="swap_next_bg",
            token_run_id=new_next_run_id,
        )

        print(f"[SWAP] sid={sid6} current={item.current_case_id} next(placeholder)={item.next_case_id}", flush=True)
        return item.current, old_run

    def materialize_next_ai_case(self, session_id: str, seed: int | None = None) -> bool:
        sid = (session_id or "").strip()
        if not sid:
            return False
        self._cleanup()
        item = self._items.get(sid)
        if not item:
            return False

        if not self._ai_enabled:
            return False

        sid6 = sid[:6]
        try:
            forced_case_id = f"ai_{sid6}_materialize_next_{int(time.time())}"
            new_case_id, new_sess = self._build_ai_session(
                sid=sid,
                seed=seed,
                stage="materialize_next",
                forced_case_id=forced_case_id,
            )
            item.next = new_sess
            item.next_case_id = new_case_id
            item.next_run_id = uuid.uuid4().hex
            item.next_prefetched_bundle = None
            item.ts = time.time()
            print(f"[NEXT] materialized ai case_id={new_case_id} sid={sid6}", flush=True)
            return True
        except Exception as e:
            if item.next:
                _set_story_meta(item.next, source="static", status="failed", stage="materialize_next", error=repr(e))
            print(f"[NEXT] materialize fail sid={sid6} err={e!r}", flush=True)
            return False
