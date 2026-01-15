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
    return {
        "contract_version": CONTRACT_V2,
        "type": msg_type,
        "payload": payload,
    }


def _emit_v2(msg_type: str, payload: JsonMap) -> None:
    _jprint(_wrap_v2(msg_type, payload))


def _emit_ui_action_ack(
    *, kind: str, action_id: str, status: str = "received", request_id: str = ""
) -> None:
    p: JsonMap = {
        "kind": kind,
        "id": action_id,
        "status": status,
    }
    if request_id:
        p["request_id"] = request_id
    _emit_v2("ui_action_ack", p)


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
            return int(v.strip())
        return default
    except Exception:
        return default


def _as_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "yes", "y"):
            return True
        if s in ("0", "false", "no", "n"):
            return False
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
    view_obj = getattr(res, "view", None)
    if view_obj is None:
        global _LAST_CHOICE_INDEXES
        _LAST_CHOICE_INDEXES = []
    return {
        "view": _node_view_to_json(view_obj),
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
    if _as_str(cmd.get("type", "")).strip() != "show_end_screen":
        return None

    meta = _as_map(cmd.get("meta"))
    options = _as_list(cmd.get("options"))
    lessons = _as_list(cmd.get("lesson"))

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

    return {
        "type": "show_end_screen",
        "end": {
            "title": _as_str(cmd.get("title", "")),
            "narration": _as_str(cmd.get("narration", "")),
            "lessons": [str(x) for x in lessons if str(x).strip()],
            "meta": {
                "node_id": _as_str(cmd.get("node_id", "")),
                "tag": _as_str(cmd.get("tag", "")),
                "v1_meta": meta,
            },
        },
        "summary": {"reasoning": reasoning},
        "actions": actions,
    }


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
    nodes = case["nodes"]
    start = _as_str(case.get("start", "")).strip()
    if (not start) or (start not in nodes):
        start = next(iter(nodes.keys()))

    return GameSession(
        state=DetectiveState(),
        nodes=nodes,
        start_node=start,
        config=config,
        solve_rule=case.get("solve_rule", {}) or {},
    )



def _emit_hello(*, case_id: str, case: JsonMap) -> None:
    _jprint(
        {
            "type": "hello",
            "case_id": case_id,
            "case_title": _as_str(case.get("title", "")),
            "start_node": _as_str(case.get("start", "")),
        }
    )


def _emit_error(message: str) -> None:
    _jprint({"type": "error", "message": message})


def _is_v2_envelope(m: JsonMap) -> bool:
    return (
        _as_str(m.get("contract_version", "")).strip() == CONTRACT_V2 and "payload" in m
    )


def _unwrap_v2_envelope(m: JsonMap) -> JsonMap:
    p = m.get("payload")
    if isinstance(p, dict):
        return {str(k): v for k, v in p.items()}
    return {}


# ------------------------------------------------------------
# Day22: end_flow dispatcher + consume flow commands (single-path)
# ------------------------------------------------------------


def _final_over_payload(*, events: list[str] | None = None) -> JsonMap:
    """Return a terminal step_result payload to unblock UI then allow bridge to exit."""
    out: JsonMap = {
        "view": {},
        "events": events or [],
        "is_over": True,
        "selected_choice_index": 0,
        "selected_next": "",
        "commands": [],
    }
    return _upgrade_commands_for_v2_envelope(out)


def _emit_replay_step(session: GameSession) -> None:
    res = session.step(PlayerAction(type="replay"))
    out = _step_result_to_json(res)
    out = _upgrade_commands_for_v2_envelope(out)
    _emit_step_v2(out)


def _dispatch_end_flow(
    *,
    end_action: str,
    session: GameSession,
    case_id: str,
    case: JsonMap,
    config: GameConfig,
    args: argparse.Namespace,
) -> Tuple[GameSession, str, JsonMap, bool]:
    """
    Central routing for end_flow.

    Returns: (new_session, new_case_id, new_case, should_exit)

    - restart_case / switch_case / quit are handled here (no apply_flow, no Flutter legacy flow).
    - others go to engine: session.step(end_flow).
    """
    a = (end_action or "").strip()

    if a == "quit":
        _emit_step_v2(_final_over_payload(events=["quit"]))
        return session, case_id, case, True

    if a == "restart_case":
        session2 = _new_session_for_case(case, config=config)
        _emit_replay_step(session2)
        return session2, case_id, case, False

    if a == "switch_case":
        new_case_id, new_case = _pick_case(None, seed=getattr(args, "seed", None))
        session2 = _new_session_for_case(new_case, config=config)
        if not getattr(args, "quiet", False):
            _emit_hello(case_id=new_case_id, case=new_case)
        _emit_replay_step(session2)
        return session2, str(new_case_id), new_case, False

    # default: let engine handle
    res = session.step(PlayerAction(type="end_flow", end_action=a))
    out = _step_result_to_json(res)
    out = _upgrade_commands_for_v2_envelope(out)

    # ✅ consume engine flow if any (e.g. engine fallback)
    session3, case_id3, case3, handled = _consume_flow_command_if_any(
        step_payload=out,
        session=session,
        case_id=case_id,
        case=case,
        config=config,
        args=args,
    )
    if handled:
        # handled path already emitted step (replay/hello/final_over)
        # decide exit based on action (consume returns should_exit via handled bool? -> handled means already done)
        # we should NOT emit `out` here.
        # exit 여부는 consume 裡面會用 dispatcher 的 should_exit 控制。
        # 여기서는 그냥 continue 동작을 위해 should_exit=False 로 보고.
        return session3, case_id3, case3, False

    _emit_step_v2(out)

    should_exit = bool(out.get("is_over")) and not (out.get("commands") or [])
    return session, case_id, case, should_exit


def _extract_flow_action(step_payload: JsonMap) -> str:
    cmds = step_payload.get("commands")
    if not isinstance(cmds, list):
        return ""
    for c in cmds:
        if isinstance(c, dict) and _as_str(c.get("type", "")).strip() == "flow":
            return _as_str(c.get("action", "")).strip()
    return ""


def _consume_flow_command_if_any(
    *,
    step_payload: JsonMap,
    session: GameSession,
    case_id: str,
    case: JsonMap,
    config: GameConfig,
    args: argparse.Namespace,
) -> Tuple[GameSession, str, JsonMap, bool]:
    """
    If step_payload contains command type=flow, handle it HERE (python side),
    and DO NOT emit the original step_payload.

    Returns: (session, case_id, case, handled)
    handled=True means we already emitted a new step_result.
    """
    action = _extract_flow_action(step_payload)
    if not action:
        return session, case_id, case, False

    _jprint({"type": "log", "msg": f"[flow_consume] action={action}"})
    session2, case_id2, case2, should_exit = _dispatch_end_flow(
        end_action=action,
        session=session,
        case_id=case_id,
        case=case,
        config=config,
        args=args,
    )
    if should_exit:
        # let caller return
        return session2, case_id2, case2, True

    return session2, case_id2, case2, True


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

    first = _step_result_to_json(session.step(PlayerAction(type="replay")))
    first = _upgrade_commands_for_v2_envelope(first)

    # ✅ also consume flow in first (just in case)
    session, case_id, case, handled = _consume_flow_command_if_any(
        step_payload=first,
        session=session,
        case_id=case_id,
        case=case,
        config=config,
        args=args,
    )
    if not handled:
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
        _jprint({"type": "log", "msg": f"stdin_recv: {req}"})

        # v2 ui_action
        if _as_str(m.get("type", "")).strip() == "ui_action":
            payload = _normalize_map(m.get("payload"))
            kind = _as_str(payload.get("kind", "")).strip()
            action_id = (
                _as_str(payload.get("id", "")).strip()
                or _as_str(payload.get("action", "")).strip()
            )
            request_id = _as_str(payload.get("request_id", "")).strip()

            _jprint(
                {
                    "type": "log",
                    "msg": f"ui_action received: kind={kind} id={action_id} request_id={request_id}",
                }
            )

            # ✅ Day23-C: 先立刻 ack（讓 Flutter 看到「已收到」）
            _emit_ui_action_ack(
                kind=kind, action_id=action_id, status="received", request_id=request_id
            )
            if kind in ("end_flow", "endFlow"):
                end_action = (
                    _as_str(payload.get("id", "")).strip()
                    or _as_str(payload.get("action", "")).strip()
                )
                session, case_id, case, should_exit = _dispatch_end_flow(
                    end_action=end_action,
                    session=session,
                    case_id=case_id,
                    case=case,
                    config=config,
                    args=args,
                )
                if should_exit:
                    return
                continue

            _emit_error(f"unknown ui_action kind: {kind}")
            continue

        if _is_v2_envelope(m):
            m = _unwrap_v2_envelope(m)

        typ = _as_str(m.get("type", "")).strip()

        # ---- choose ----
        if typ == "choose":
            idx = _as_int(m.get("choice_index"), 0)
            idx0 = idx

            if _LAST_CHOICE_INDEXES:
                if idx in _LAST_CHOICE_INDEXES:
                    idx0 = idx
                elif (idx - 1) in _LAST_CHOICE_INDEXES:
                    idx0 = idx - 1
                elif (idx + 1) in _LAST_CHOICE_INDEXES:
                    idx0 = idx + 1
                else:
                    idx0 = idx
            else:
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

            session, case_id, case, handled = _consume_flow_command_if_any(
                step_payload=out,
                session=session,
                case_id=case_id,
                case=case,
                config=config,
                args=args,
            )
            if handled:
                # flow handled already emitted new step_result
                continue

            _emit_step_v2(out)
            if out.get("is_over") and not (out.get("commands") or []):
                return
            continue

        # ---- replay ----
        if typ == "replay":
            res = session.step(PlayerAction(type="replay"))
            out = _step_result_to_json(res)
            out = _upgrade_commands_for_v2_envelope(out)

            session, case_id, case, handled = _consume_flow_command_if_any(
                step_payload=out,
                session=session,
                case_id=case_id,
                case=case,
                config=config,
                args=args,
            )
            if handled:
                continue

            _emit_step_v2(out)
            if out.get("is_over") and not (out.get("commands") or []):
                return
            continue

        # ---- quit ----
        if typ == "quit":
            res = session.step(PlayerAction(type="quit"))
            out = _step_result_to_json(res)
            out = _upgrade_commands_for_v2_envelope(out)
            _emit_step_v2(out)
            return

        # ---- set_reasons ----
        if typ == "set_reasons":
            reason_ids = m.get("reason_ids") or []
            if not isinstance(reason_ids, list):
                reason_ids = []
            reason_ids = [str(x).strip() for x in reason_ids if str(x).strip()]

            reason_text = _as_str(m.get("reason_text", "")).strip()

            res = session.step(
                PlayerAction(
                    type="set_reasons",
                    reason_ids=reason_ids,
                    reason_text=reason_text,
                )
            )
            out = _step_result_to_json(res)
            out = _upgrade_commands_for_v2_envelope(out)

            session, case_id, case, handled = _consume_flow_command_if_any(
                step_payload=out,
                session=session,
                case_id=case_id,
                case=case,
                config=config,
                args=args,
            )
            if handled:
                continue

            _emit_step_v2(out)
            if out.get("is_over") and not (out.get("commands") or []):
                return
            continue

        # ---- confirm_quiz_answer ----
        if typ == "confirm_quiz_answer":
            answers = m.get("answers") or []
            if not isinstance(answers, list):
                answers = []
            skipped = _as_bool(m.get("skipped"), False)

            try:
                res = session.step(
                    PlayerAction(
                        type="confirm_quiz_answer", answers=answers, skipped=skipped
                    )
                )
            except Exception as e:
                _emit_error(
                    f"confirm_quiz_failed: answers={answers} skipped={skipped} err={e}"
                )
                continue

            out = _step_result_to_json(res)
            out = _upgrade_commands_for_v2_envelope(out)

            session, case_id, case, handled = _consume_flow_command_if_any(
                step_payload=out,
                session=session,
                case_id=case_id,
                case=case,
                config=config,
                args=args,
            )
            if handled:
                continue

            _emit_step_v2(out)
            if out.get("is_over") and not (out.get("commands") or []):
                return
            continue

        # ---- end_flow (legacy direct) ----
        if typ == "end_flow":
            end_action = (
                _as_str(m.get("action", "")).strip()
                or _as_str(m.get("end_action", "")).strip()
            )
            session, case_id, case, should_exit = _dispatch_end_flow(
                end_action=end_action,
                session=session,
                case_id=case_id,
                case=case,
                config=config,
                args=args,
            )
            if should_exit:
                return
            continue

        # ---- apply_flow (legacy; keep for backward compatibility) ----
        if typ == "apply_flow":
            action = _as_str(m.get("action", "")).strip()
            if action == "quit":
                _jprint({"type": "ok", "action": "quit"})
                return
            if action == "restart_case":
                session = _new_session_for_case(case, config=config)
                _jprint({"type": "ok", "action": "restart_case"})
                _emit_replay_step(session)
                continue
            if action == "switch_case":
                case_id, case = _pick_case(None, seed=args.seed)
                session = _new_session_for_case(case, config=config)
                if not args.quiet:
                    _emit_hello(case_id=case_id, case=case)
                _jprint({"type": "ok", "action": "switch_case"})
                _emit_replay_step(session)
                continue

            _emit_error(f"unknown apply_flow action: {action}")
            continue

        _emit_error(f"unknown_type: {typ}")


if __name__ == "__main__":
    main()
