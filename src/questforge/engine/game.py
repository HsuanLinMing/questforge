from __future__ import annotations

from typing import Optional

from questforge.cli.cli_commands import cli_handle_ask_reason, handle_cli_command
from questforge.cli.cli_render import render_view, show_status, trace
from questforge.engine.actions import PlayerAction
from questforge.engine.case_selector import CaseSelector
from questforge.engine.confirm_quiz import run_confirm_quiz
from questforge.engine.save_manager import SaveManager
from questforge.engine.session import GameSession
from questforge.core.models import DetectiveState, GameConfig
from questforge.content.cases import CASES


def _handle_commands(session: GameSession, res, *, on_flow) -> None:
    for cmd in res.commands or []:
        t = cmd.get("type")

        if t == "ask_reason":
            action = cli_handle_ask_reason(cmd)
            res2 = session.step(action)
            for e in res2.events:
                print("\n" + e)
            _handle_commands(session, res2, on_flow=on_flow)
            continue

        if t == "confirm_quiz":
            quiz = cmd.get("quiz") or []
            _ = run_confirm_quiz(quiz, collected=set(session.state.clues))
            continue

        if t == "flow":
            on_flow(cmd.get("action") or "")
            continue


def game_loop_v6(config: GameConfig | None = None) -> None:
    selector = CaseSelector(CASES)
    save_mgr = SaveManager(CASES)
    config = config or GameConfig()

    case_id, case = selector.pick()
    session = GameSession(
        state=DetectiveState(),
        nodes=case["nodes"],
        start_node=case["start"],
        config=config,
        solve_rule=case.get("solve_rule", {}) or {},
    )

    print("\n歡迎來到《QuestForge：霏霏＆樂樂小偵探》！")
    print(f"本次案件：{case['title']}\n")

    chosen_idx: Optional[int] = None

    def on_flow(action: str) -> None:
        nonlocal session, case_id, case, config, chosen_idx

        action = (action or "").strip()
        if action == "quit":
            raise SystemExit

        if action == "restart_case":
            session = GameSession(
                state=DetectiveState(),
                nodes=case["nodes"],
                start_node=case["start"],
                config=config,
                solve_rule=case.get("solve_rule", {}) or {},
            )
            chosen_idx = None
            return

        if action == "switch_case":
            case_id2, case2 = selector.pick()
            case_id, case = case_id2, case2
            session = GameSession(
                state=DetectiveState(),
                nodes=case["nodes"],
                start_node=case["start"],
                config=config,
                solve_rule=case.get("solve_rule", {}) or {},
            )
            chosen_idx = None
            print(f"\n切換案件：{case['title']}\n")
            return

    while True:
        # 1) view
        try:
            view = session.get_view()
        except KeyError:
            print(
                f"\n[錯誤] 找不到節點：{session.current}（可能存檔版本或案件節點已變更）"
            )
            return

        trace(
            state=session.state,
            case_title=case["title"],
            current=session.current,
            chosen_idx=chosen_idx,
        )
        show_status(session.state)
        render_view(view)

        raw = input("\n請選擇：").strip().lower()

        # 2) CLI commands（S/L/Q 等）
        chosen_idx_ref = {"value": chosen_idx}
        handled, new_session, new_case_id, new_case, new_config = handle_cli_command(
            raw,
            save_mgr=save_mgr,
            session=session,
            case_id=case_id,
            case=case,
            config=config,
            chosen_idx_ref=chosen_idx_ref,
        )
        if handled:
            if new_session is None:
                try:
                    save_mgr.save_autosave(
                        session=session,
                        case_id=case_id,
                        case_title=case["title"],
                        config=config,
                    )
                except Exception:
                    pass
                return

            session = new_session
            case_id = new_case_id
            case = new_case
            config = new_config
            chosen_idx = chosen_idx_ref["value"]
            continue

        # 3) Normal node：raw 必須是數字
        if not raw.isdigit():
            print("輸入不正確喔～請輸入選項數字，或 C / N / P / R / S / L / Q。")
            continue

        idx = int(raw)
        chosen_idx = idx

        res = session.step(PlayerAction(type="choose", choice_index=idx))

        # 每回合自動存檔
        try:
            save_mgr.save_autosave(
                session=session,
                case_id=case_id,
                case_title=case["title"],
                config=config,
            )
        except Exception:
            pass

        for e in res.events:
            print("\n" + e)

        _handle_commands(session, res, on_flow=on_flow)

        # flow 會用 is_over=True 讓 CLI 走 on_flow 後回到 while 開頭
        # 一般故事真的結束才 return
        if res.is_over:
            # 若是 flow 已被處理，通常會 restart/switch，或 raise SystemExit
            # 走到這裡代表真的結束（例如 next_id 空）
            return
