from __future__ import annotations

from typing import Any, Dict, Optional
import json
from pathlib import Path

from questforge.cli.cli_commands import cli_handle_ask_reason, handle_cli_command
from questforge.cli.cli_render import render_view, show_status, trace
from questforge.engine.case_selector import CaseSelector
from questforge.engine.confirm_quiz import run_confirm_quiz
from questforge.engine.actions import PlayerAction
from questforge.core.models import DetectiveState, GameConfig
from questforge.content.cases import CASES
from questforge.engine.save_manager import SaveManager
from questforge.engine.session import GameSession, restore_session_from_snapshot


def game_loop_v6(config: GameConfig | None = None) -> None:
    """Day6+：CLI adapter（input/print），核心推進交給 GameSession。

    ✅ Day7：turn 改由 GameSession 統一管理（choose 時 +1）
    ✅ Day7：指認 accuse_node 規則已在 GameSession（session.py）
    ✅ Day7-C：CLI commands / SaveManager 拆分
    """
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

    chosen_idx: Optional[int] = None  # 只用於 trace 顯示（上一回合選了什麼）

    while True:
        # ✅ 0) 先處理「command-only 節點」（例如 reason_node）
        reason_node = str(
            (case.get("solve_rule", {}) or {}).get("reason_node") or ""
        ).strip()
        if reason_node and session.current == reason_node:
            # 觸發 step 讓引擎吐出 ask_reason command
            res0 = session.step(PlayerAction(type="choose", choice_index=0))

            # events
            for e in res0.events:
                print("\n" + e)

            # commands
            for cmd in res0.commands or []:
                if cmd.get("type") == "ask_reason":
                    action = cli_handle_ask_reason(cmd)
                    res2 = session.step(action)
                    for e in res2.events:
                        print("\n" + e)

            # 消耗完 command 後，回到 while 顯示下一個 view
            continue
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
        if not view.choices:
            # 沒有選項就代表這個節點可能是純敘事或結尾
            # 先讓使用者按 Enter 繼續，避免直接退出
            _ = input("\n（按 Enter 繼續）").strip()
            # 你也可以在這裡選擇自動結束，依你的 node 規則而定
            return
        raw = input("\n請選擇：").strip().lower()

        # 2) CLI commands（集中處理）
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
            # q 結束：handle_cli_command 會回 new_session=None
            if new_session is None:
                # ✅ 你要的：離開前 autosave（就算 handle_cli_command 也做了，這裡再保險一次）
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

            # 其他指令（r/c/n/s/l/p）完成，更新狀態並 continue
            session = new_session
            case_id = new_case_id
            case = new_case
            config = new_config
            chosen_idx = chosen_idx_ref["value"]
            continue

        # 3) choose（數字）
        if not raw.isdigit():
            print("輸入不正確喔～請輸入選項數字，或 C / N / P / R / S / L / Q。")
            continue

        idx = int(raw)
        if idx <= 0 or idx > len(view.choices):
            print("輸入不正確喔～請輸入有效的選項數字。")
            continue

        chosen_idx = idx
        res = session.step(PlayerAction(type="choose", choice_index=idx))

        # ✅ 每回合自動存檔（建議）
        try:
            save_mgr.save_autosave(
                session=session,
                case_id=case_id,
                case_title=case["title"],
                config=config,
            )
        except Exception:
            pass

        # events
        for e in res.events:
            print("\n" + e)

        # commands
        for cmd in res.commands or []:
            if cmd.get("type") == "confirm_quiz":
                quiz = cmd.get("quiz") or []
                picked = run_confirm_quiz(quiz, collected=set(session.state.clues))
                # 如果你想把 picked 存起來（可選），可以：
                # session.state.notes.extend(picked)  # 看你 state 有沒有 notes
                continue

            if cmd.get("type") == "ask_reason":
                action = cli_handle_ask_reason(cmd)
                res2 = session.step(action)

                for e in res2.events:
                    print("\n" + e)

        if res.is_over:
            return
