# src/questforge_server/session_store.py
from __future__ import annotations

import json
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
    """
    AI 生成失敗時，落盤 last_failed，方便你直接打開看：
      - .qf_cache/generated_stories/last_failed.txt
      - .qf_cache/generated_stories/last_failed_meta.json
    """
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
        return case_id, GameSession(
            state=state,
            nodes=nodes,
            start_node=start_node,
            config=config,
            solve_rule=solve_rule,
        )

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
        """
        stage: create_current / create_next_bg / reset_current / swap_next_bg / materialize_next
        forced_case_id: 強制唯一，避免 dump 被覆蓋
        """
        sid6 = (sid or "")[:6]
        try:
            print(f"[AI_BUILD] stage={stage} sid={sid6} seed={seed} forced_case_id={forced_case_id}", flush=True)
            pkg = self._gen.generate(seed=seed, forced_case_id=forced_case_id)
            sess, _solve_rule = build_game_session_from_story_nodes(pkg=pkg, seed=seed)

            case_id = (pkg.meta.case_id or "").strip() or forced_case_id
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
        """
        背景生成 next（不阻塞 create/swap）
        - 用 token_run_id 做「本次 next 版本」鎖定：若 next 已被 swap/重置，背景結果不覆寫
        """
        sid6 = (sid or "")[:6]

        def _job() -> None:
            try:
                # 生成完時再確認 session 還在、token 還一致
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
                print(f"[AI_BG] sid={sid6} fail stage={stage} err={e!r}", flush=True)

        t = threading.Thread(target=_job, name=f"qf_ai_next_{sid6}", daemon=True)
        t.start()

    # ----------------------------
    # Public: create/reset/swap
    # ----------------------------
    def create(self, seed: int | None = None) -> Tuple[str, GameSession]:
        """
        ✅ 你要的行為：
        - current：同步 AI（馬上進遊戲要能玩）
        - next：先放靜態 CASES（立即有 next），並在背景生成 AI next 覆蓋掉
        """
        self._cleanup()
        sid = uuid.uuid4().hex
        sid6 = sid[:6]
        t0 = time.time()
        print(f"[START] sid={sid6} +0.00s create_session:begin seed={seed}", flush=True)

        # A: current（同步 AI；失敗 fallback CASES）
        try:
            forced_case_id = f"ai_{sid6}_create_current_{int(time.time())}"
            case_a, sess_a = self._build_ai_session(
                sid=sid,
                seed=seed,
                stage="create_current",
                forced_case_id=forced_case_id,
            )
        except Exception as e:
            print(f"[AI] create_current fallback sid={sid6}: {e!r}", flush=True)
            case_a, _ = self._pick_two_cases()
            case_a, sess_a = self._build_session(case_id=case_a, seed=seed)

        # B: next（先用靜態，背景 AI 覆蓋）
        case_b, _ = self._pick_two_cases()
        if case_b == case_a:
            case_b, _ = self._pick_two_cases()
        case_b, sess_b = self._build_session(case_id=case_b, seed=seed)

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
        """重開 current（保留 next 不動）。回傳 (new_session, old_current_run_id_to_delete)"""
        sid = (session_id or "").strip()
        if not sid:
            return None, None
        self._cleanup()
        item = self._items.get(sid)
        if not item:
            return None, None

        sid6 = sid[:6]
        old_run = item.current_run_id

        try:
            forced_case_id = f"ai_{sid6}_reset_current_{int(time.time())}"
            new_case_id, sess = self._build_ai_session(
                sid=sid,
                seed=seed,
                stage="reset_current",
                forced_case_id=forced_case_id,
            )
        except Exception as e:
            print(f"[AI] reset_current fallback sid={sid6}: {e!r}", flush=True)
            new_case_id, sess = self._build_session(case_id=case_id, seed=seed)

        item.current = sess
        item.current_case_id = new_case_id
        item.current_run_id = uuid.uuid4().hex
        item.ts = time.time()
        return sess, old_run

    # ✅ backward-compatible alias（routes_game 目前叫 store.reset）
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
        """
        ✅ promotion：next -> current（立即）
        ✅ 新 next：先靜態 placeholder，背景生成 AI 覆蓋
        """
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
        item.current_run_id = item.next_run_id  # ✅ run_id 一起 promote

        # new next：先放靜態（立即可用）
        selector = CaseSelector(CASES)
        new_case, _ = selector.pick()
        if new_case == item.current_case_id:
            all_ids = list(CASES.keys())
            candidates = [x for x in all_ids if x != item.current_case_id]
            if candidates:
                new_case = candidates[int(time.time()) % len(candidates)]
        new_case, new_sess = self._build_session(case_id=new_case, seed=seed)

        # 先放 placeholder
        new_next_run_id = uuid.uuid4().hex
        item.next = new_sess
        item.next_case_id = new_case
        item.next_run_id = new_next_run_id
        item.next_prefetched_bundle = None
        item.ts = time.time()

        # ✅ 背景生成 AI next 覆蓋（不阻塞）
        self._spawn_build_next_in_background(
            sid=sid,
            seed=seed,
            stage="swap_next_bg",
            token_run_id=new_next_run_id,
        )

        print(f"[SWAP] sid={sid6} current={item.current_case_id} next(placeholder)={item.next_case_id}", flush=True)
        return item.current, old_run

    def materialize_next_ai_case(self, session_id: str, seed: int | None = None) -> bool:
        """
        手動強制把 next 轉成 AI（同步，給 debug 或你想立刻測）
        """
        sid = (session_id or "").strip()
        if not sid:
            return False
        self._cleanup()
        item = self._items.get(sid)
        if not item:
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
            print(f"[NEXT] materialize fail sid={sid6} err={e!r}", flush=True)
            return False
