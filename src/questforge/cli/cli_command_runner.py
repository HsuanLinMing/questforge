# src/questforge/cli/cli_command_runner.py
from __future__ import annotations

from typing import Any, Dict, Optional

from questforge.engine.actions import PlayerAction
from questforge.engine.session import GameSession
from questforge.cli.cli_commands import cli_handle_ask_reason


def run_single_command(*, session: GameSession, command: Dict[str, Any]) -> Optional[PlayerAction]:
    ctype = (command.get("type") or "").strip()

    if ctype == "ask_reason":
        return cli_handle_ask_reason(command)

    # 先保留：Day16-C end screen（你若已有 UI 顯示就接你的函式）
    if ctype == "show_end_screen":
        _print_end_screen(command)
        # CLI 這裡要讀玩家選項，回傳 end_flow
        end_action = _read_end_action(command)
        return PlayerAction(type="end_flow", end_action=end_action)

    # confirm_quiz 若你已有 run_confirm_quiz，可以接回 action
    if ctype == "confirm_quiz":
        # TODO: 若你 Day16 已經有 run_confirm_quiz(session.state, quiz) 類似的，就接起來
        _print_quiz_hint(command)
        return None

    # flow: restart_case / switch_case / quit 這種（engine end_flow 回傳的 commands）
    if ctype == "flow":
        act = (command.get("action") or "").strip()
        if act == "quit":
            return PlayerAction(type="quit")
        # restart/switch 你可能是在外層 game_loop 做 case selector
        # 先回傳 quit 或 None，交給外層處理
        return None

    return None


def _print_end_screen(cmd: Dict[str, Any]) -> None:
    print("\n====================")
    print(f"【{cmd.get('title','')}】")
    print(cmd.get("narration", ""))
    lesson = cmd.get("lesson") or []
    if lesson:
        print("\n【小提醒】")
        for ln in lesson:
            print(f"- {ln}")
    print("====================\n")


def _read_end_action(cmd: Dict[str, Any]) -> str:
    opts = cmd.get("options") or []
    for i, o in enumerate(opts, start=1):
        print(f"{i}. {(o.get('text') or '').strip()}")

    raw = input("請選擇：").strip()
    try:
        idx = int(raw)
    except Exception:
        idx = 0

    if idx <= 0 or idx > len(opts):
        return "quit"
    return (opts[idx - 1].get("id") or "quit").strip()


def _print_quiz_hint(cmd: Dict[str, Any]) -> None:
    print("\n[confirm_quiz]（Day17-A 先不處理也可以）")
