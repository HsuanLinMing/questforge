from __future__ import annotations

from typing import Any, Dict, Optional
import json
from pathlib import Path

from questforge.cli.cli_commands import handle_cli_command
from questforge.cli.cli_render import render_view, show_status, trace
from questforge.engine.case_selector import CaseSelector
from questforge.engine.confirm_quiz import run_confirm_quiz
from questforge.engine.session import GameSession
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
                run_confirm_quiz(...)
            elif cmd.get("type") == "ask_reason":
                mode = (cmd.get("mode") or "choice").strip()
                options = cmd.get("options") or []

                if mode == "choice":
                    print("\n【你為什麼這樣想？選出你的線索】")
                    for i, opt in enumerate(options, start=1):
                        print(f"{i}. {opt.get('text','')}")
                    raw2 = input("請選擇理由：").strip()
                    if not raw2.isdigit() or not (1 <= int(raw2) <= len(options)):
                        print("輸入不正確，先幫你選『我說不太清楚』。")
                        reason_id = "unspecified"
                    else:
                        reason_id = (
                            options[int(raw2) - 1].get("id") or ""
                        ).strip() or "unspecified"

                    # 回送引擎
                    res2 = session.step(
                        PlayerAction(type="set_reason", reason_id=reason_id)
                    )
                    for e in res2.events:
                        print("\n" + e)

                elif mode == "text":
                    text = input("\n用一句話說說你的理由（可留空）：").strip()
                    res2 = session.step(
                        PlayerAction(
                            type="set_reason", reason_id="free_text", reason_text=text
                        )
                    )
                    for e in res2.events:
                        print("\n" + e)

                elif mode == "voice":
                    print("\n（語音模式先預留：CLI 暫不支援錄音，先當作文字輸入）")
                    text = input("請用文字代替語音說明（可留空）：").strip()
                    res2 = session.step(
                        PlayerAction(
                            type="set_reason", reason_id="voice_text", reason_text=text
                        )
                    )
                    for e in res2.events:
                        print("\n" + e)

        if res.is_over:
            return
