# src/questforge/cli/json_bridge.py
from __future__ import annotations

import argparse
import json
import random
import sys
from typing import Any, Dict, Optional, Tuple

from questforge.content.cases import CASES
from questforge.core.models import DetectiveState, GameConfig
from questforge.engine.actions import PlayerAction
from questforge.engine.case_selector import CaseSelector
from questforge.engine.session import GameSession


JsonMap = Dict[str, Any]

CONTRACT_V2 = "ui_contract_v2"
_LAST_CHOICE_INDEXES: list[int] = []


def _jprint(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _wrap_v2(msg_type: str, payload: JsonMap) -> JsonMap:
    # v2 envelope (engine -> UI)
    return {
        "contract_version": CONTRACT_V2,
        "type": msg_type,  # "step_result" | "command" | "event" (我們先用 step_result)
        "payload": payload,
    }


def _emit_step_v2(step_payload: JsonMap) -> None:
    _jprint(_wrap_v2("step_result", step_payload))


def _as_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        if isinstance(v, str):
            x = int(v.strip())
            return x
        return default
    except Exception:
        return default


def _as_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    if isinstance(v, str):
        return v
    return str(v)


def _normalize_map(v: Any) -> JsonMap:
    if isinstance(v, dict):
        return {str(k): v2 for k, v2 in v.items()}
    return {}


def _node_view_to_json(view: Any) -> JsonMap:
    global _LAST_CHOICE_INDEXES

    if view is None:
        _LAST_CHOICE_INDEXES = []
        return {}

    choices_out = []
    idxs: list[int] = []

    for c in getattr(view, "choices", []) or []:
        ci = int(getattr(c, "index", 0) or 0)
        idxs.append(ci)
        choices_out.append(
            {
                "index": ci,
                "text": _as_str(getattr(c, "text", "")),
                "enabled": bool(getattr(c, "enabled", True)),
                "reason": getattr(c, "reason", None),
                "tag": _as_str(getattr(c, "tag", "")),
            }
        )

    _LAST_CHOICE_INDEXES = idxs

    return {
        "node_id": _as_str(getattr(view, "node_id", "")),
        "title": _as_str(getattr(view, "title", "")),
        "narration": _as_str(getattr(view, "narration", "")),
        "choices": choices_out,
        "can_replay": True,
        "can_quit": True,
    }


def _step_result_to_json(res: Any) -> JsonMap:
    return {
        "view": _node_view_to_json(getattr(res, "view", None)),
        "events": list(getattr(res, "events", []) or []),
        "is_over": bool(getattr(res, "is_over", False)),
        "selected_choice_index": int(getattr(res, "selected_choice_index", 0) or 0),
        "selected_next": _as_str(getattr(res, "selected_next", "")),
        "commands": list(getattr(res, "commands", []) or []),
    }


def _as_list(v: Any) -> list:
    return v if isinstance(v, list) else []


def _as_map(v: Any) -> JsonMap:
    return v if isinstance(v, dict) else {}


def _upgrade_show_end_screen_v1_to_v2(cmd: JsonMap) -> Optional[JsonMap]:
    # v1 show_end_screen payload:
    # {type,node_id,tag,title,narration,lesson[],options[],meta{reasoning_contract_v1...}}
    if _as_str(cmd.get("type", "")).strip() != "show_end_screen":
        return None

    meta = _as_map(cmd.get("meta"))
    options = _as_list(cmd.get("options"))
    lessons = _as_list(cmd.get("lesson"))

    # actions (UI -> engine)
    actions = []
    for opt in options:
        o = _as_map(opt)
        oid = _as_str(o.get("id", "")).strip()
        txt = _as_str(o.get("text", "")).strip()
        if oid or txt:
            actions.append({"id": oid, "text": txt, "kind": "end_flow"})

    reasoning = {
        "case_title": _as_str(meta.get("case_title", "")),
        "turn": _as_int(meta.get("turn", 0), 0),
        "accused": _as_str(meta.get("accused", "")),
        "reason": {
            "mode": _as_str(meta.get("reason_mode", "")) or "choice",
            "selected_observation_ids": [
                str(x) for x in _as_list(meta.get("reason_ids")) if str(x).strip()
            ],
            "text": _as_str(meta.get("reason_text", "")),
        },
        "clues_preview": [
            str(x) for x in _as_list(meta.get("clues_preview")) if str(x).strip()
        ],
        "evaluation": {
            "level": _as_str(meta.get("level", "")),
            "score": _as_int(meta.get("score", 0), 0),
            "threshold": _as_int(meta.get("threshold", 0), 0),
            "engine_message": _as_str(meta.get("engine_message", "")),
        },
        "matched_evidence": [
            {"id": "", "text": str(x)}
            for x in _as_list(meta.get("matched_evidence"))
            if str(x).strip()
        ],
        "missing_key_evidence": [
            {"id": "", "text": str(x)}
            for x in _as_list(meta.get("missing_key_evidence"))
            if str(x).strip()
        ],
    }

    v2 = {
        "type": "show_end_screen",
        "end": {
            "title": _as_str(cmd.get("title", "")),
            "narration": _as_str(cmd.get("narration", "")),
            "lessons": [str(x) for x in lessons if str(x).strip()],
            "meta": {
                "node_id": _as_str(cmd.get("node_id", "")),
                "tag": _as_str(cmd.get("tag", "")),
                # 你想保留原 meta 也可以塞進來（debug 用）
                "v1_meta": meta,
            },
        },
        "summary": {"reasoning": reasoning},
        "actions": actions,
    }
    return v2


def _upgrade_commands_for_v2_envelope(step_payload: JsonMap) -> JsonMap:
    cmds = step_payload.get("commands")
    if not isinstance(cmds, list):
        return step_payload

    out_cmds = []
    for x in cmds:
        if isinstance(x, dict):
            upgraded = _upgrade_show_end_screen_v1_to_v2(x)
            out_cmds.append(upgraded if upgraded is not None else x)
        else:
            out_cmds.append(x)

    step_payload["commands"] = out_cmds
    return step_payload


def _pick_case(case_id: Optional[str], *, seed: Optional[int]) -> Tuple[str, JsonMap]:
    if seed is not None:
        random.seed(seed)

    if case_id:
        cid = str(case_id).strip()
        if cid not in CASES:
            raise SystemExit(f"[json_bridge] unknown case_id: {cid}")
        return cid, CASES[cid]

    selector = CaseSelector(CASES)
    cid2, case2 = selector.pick()
    return str(cid2), case2


def _new_session_for_case(case: JsonMap, *, config: GameConfig) -> GameSession:
    return GameSession(
        state=DetectiveState(),
        nodes=case["nodes"],
        start_node=case["start"],
        config=config,
        solve_rule=case.get("solve_rule", {}) or {},
    )


def _emit_hello(*, case_id: str, case: JsonMap) -> None:
    # hello 維持舊格式（dev log 用）
    _jprint(
        {
            "type": "hello",
            "case_id": case_id,
            "case_title": _as_str(case.get("title", "")),
            "start_node": _as_str(case.get("start", "")),
        }
    )


def _emit_error(message: str) -> None:
    # error 維持舊格式（dev log 用）
    _jprint({"type": "error", "message": message})


def _is_v2_envelope(m: JsonMap) -> bool:
    return (
        _as_str(m.get("contract_version", "")).strip() == CONTRACT_V2 and "payload" in m
    )


def _unwrap_v2_envelope(m: JsonMap) -> JsonMap:
    # returns payload
    p = m.get("payload")
    if isinstance(p, dict):
        return {str(k): v for k, v in p.items()}
    return {}


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m questforge.cli.json_bridge")
    ap.add_argument(
        "--case", dest="case_id", default=None, help="指定案件 id（例如 2）"
    )
    ap.add_argument("--seed", dest="seed", type=int, default=None, help="固定抽案 seed")
    ap.add_argument("--quiet", action="store_true", help="不輸出 hello（測試用）")
    args = ap.parse_args(argv)

    config = GameConfig()

    case_id, case = _pick_case(args.case_id, seed=args.seed)
    session = _new_session_for_case(case, config=config)

    if not args.quiet:
        _emit_hello(case_id=case_id, case=case)

    # 初始 view：改成 v2 envelope(step_result)
    first = _step_result_to_json(session.step(PlayerAction(type="replay")))
    _emit_step_v2(first)

    while True:
        line = sys.stdin.readline()
        if not line:
            return

        raw = line.strip()

        if not raw:
            continue

        if raw.startswith("\x1b[") or raw.startswith("^[["):
            continue

        try:
            req = json.loads(raw)
        except Exception as e:
            _emit_error(f"invalid_json: {e}")
            continue

        m = _normalize_map(req)

        # ----------------------------
        # v2 UI action support:
        # { "type":"ui_action", "payload": { "kind":"end_flow", "id":"go_epilogue" } }
        # ----------------------------
        if _as_str(m.get("type", "")).strip() == "ui_action":
            payload = _normalize_map(m.get("payload"))
            kind = _as_str(payload.get("kind", "")).strip()
            if kind == "end_flow":
                end_action = _as_str(payload.get("id", "")).strip()
                res = session.step(PlayerAction(type="end_flow", end_action=end_action))
                out = _step_result_to_json(res)
                out = _upgrade_commands_for_v2_envelope(out)
                _emit_step_v2(out)
                if out.get("is_over") and not (out.get("commands") or []):
                    return
                continue

            _emit_error(f"unknown ui_action kind: {kind}")
            continue

        # ----------------------------
        # optional: if someday UI sends a v2 envelope, we can unwrap it
        # e.g. {contract_version,type:"event",payload:{type:"choose"...}}
        # ----------------------------
        if _is_v2_envelope(m):
            # interpret payload as request object
            m = _unwrap_v2_envelope(m)

        typ = _as_str(m.get("type", "")).strip()

        # ---- client actions -> PlayerAction ----
        if typ == "choose":
            idx = _as_int(m.get("choice_index"), 0)

            # ✅ 引擎多半吃的是 ChoiceView.index（顯示用 index），不是 list position
            # 我們做 0-based / 1-based 兼容，但「最後送回引擎的仍是 index 值」
            idx0 = idx

            if _LAST_CHOICE_INDEXES:
                if idx in _LAST_CHOICE_INDEXES:
                    # UI 送的就是顯示 index（最常見：1,2,3...）
                    idx0 = idx
                elif (idx - 1) in _LAST_CHOICE_INDEXES:
                    # UI 送 1-based，但 choices 是 0-based
                    idx0 = idx - 1
                elif (idx + 1) in _LAST_CHOICE_INDEXES:
                    # UI 送 0-based，但 choices 是 1-based
                    idx0 = idx + 1
                else:
                    # 找不到就不亂轉，直接丟出去，讓引擎自己報錯/忽略
                    idx0 = idx
            else:
                # 沒有 last view 可用：保守不轉
                idx0 = idx

            try:
                _jprint(
                    {
                        "type": "log",
                        "msg": f"choose: idx={idx} -> idx0={idx0}, last={_LAST_CHOICE_INDEXES}",
                    }
                )
                res = session.step(PlayerAction(type="choose", choice_index=idx0))
            except Exception as e:
                _emit_error(
                    f"choose_failed: idx={idx} idx0={idx0} last={_LAST_CHOICE_INDEXES} err={e}"
                )
                continue

            out = _step_result_to_json(res)
            out = _upgrade_commands_for_v2_envelope(out)
            _emit_step_v2(out)

            if out.get("is_over") and not (out.get("commands") or []):
                return
            continue

        if typ == "replay":
            res = session.step(PlayerAction(type="replay"))
            out = _step_result_to_json(res)
            out = _upgrade_commands_for_v2_envelope(out)
            _emit_step_v2(out)

            if out.get("is_over") and not (out.get("commands") or []):
                return
            continue

        if typ == "quit":
            res = session.step(PlayerAction(type="quit"))
            out = _step_result_to_json(res)
            out = _upgrade_commands_for_v2_envelope(out)
            _emit_step_v2(out)

            return

        if typ == "set_reasons":
            reason_ids = m.get("reason_ids") or []
            if not isinstance(reason_ids, list):
                reason_ids = []
            reason_ids = [str(x).strip() for x in reason_ids if str(x).strip()]

            reason_text = _as_str(m.get("reason_text", "")).strip()
            res = session.step(
                PlayerAction(
                    type="set_reasons", reason_ids=reason_ids, reason_text=reason_text
                )
            )
            out = _step_result_to_json(res)
            out = _upgrade_commands_for_v2_envelope(out)
            _emit_step_v2(out)

            if out.get("is_over") and not (out.get("commands") or []):
                return
            continue

        if typ == "end_flow":
            # ✅ 相容你的 Flutter：
            # - Day20 Preview: {"type":"end_flow","action":"go_epilogue"}
            # - Old: {"type":"end_flow","end_action":"go_epilogue"}
            end_action = (
                _as_str(m.get("action", "")).strip()
                or _as_str(m.get("end_action", "")).strip()
            )
            res = session.step(PlayerAction(type="end_flow", end_action=end_action))
            out = _step_result_to_json(res)
            out = _upgrade_commands_for_v2_envelope(out)
            _emit_step_v2(out)
            if out.get("is_over") and not (out.get("commands") or []):
                return
            continue

        # apply_flow（dev utility）仍保留舊格式 ok + step_result(v2)
        if typ == "apply_flow":
            action = _as_str(m.get("action", "")).strip()
            if action == "quit":
                _jprint({"type": "ok", "action": "quit"})
                return
            if action == "restart_case":
                session = _new_session_for_case(case, config=config)
                _jprint({"type": "ok", "action": "restart_case"})
                _emit_step_v2(
                    _step_result_to_json(session.step(PlayerAction(type="replay")))
                )
                continue
            if action == "switch_case":
                case_id, case = _pick_case(None, seed=args.seed)
                session = _new_session_for_case(case, config=config)
                if not args.quiet:
                    _emit_hello(case_id=case_id, case=case)
                _jprint({"type": "ok", "action": "switch_case"})
                _emit_step_v2(
                    _step_result_to_json(session.step(PlayerAction(type="replay")))
                )
                continue

            _emit_error(f"unknown apply_flow action: {action}")
            continue

        _emit_error(f"unknown_type: {typ}")


if __name__ == "__main__":
    main()
