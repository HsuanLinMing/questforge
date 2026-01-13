from __future__ import annotations

from typing import Optional

from questforge.cli.cli_commands import (
    cli_handle_ask_reason,
    cli_handle_ask_reason_dispatch,
    handle_cli_command,
)
from questforge.cli.cli_render import render_view, show_status, trace
from questforge.engine.actions import PlayerAction
from questforge.engine.case_selector import CaseSelector
from questforge.engine.confirm_quiz import run_confirm_quiz
from questforge.engine.save_manager import SaveManager
from questforge.engine.session import GameSession
from questforge.core.models import DetectiveState, GameConfig
from questforge.content.cases import CASES


def _handle_commands(session: GameSession, res, *, on_flow) -> bool:
    """
    回傳 True 代表發生 flow（restart/switch/quit），外層要立刻 continue 重新 render。
    """
    while res.commands:
        cmds = list(res.commands or [])
        res.commands = []  # 防止同一批被重跑（保守寫法）

        for cmd in cmds:
            t = (cmd.get("type") or "").strip()

            if t == "ask_reason":
                action = cli_handle_ask_reason_dispatch(cmd)  # ✅ 新的
                res = session.step(action)
                if res is None:
                    print(
                        "\n[BUG] session.step() 回傳 None（ask_reason -> set_reasons）"
                    )
                    return False
                for e in res.events:
                    print("\n" + e)

                # 可能 step 後又產生新 commands，所以回到 while
                break

            if t == "confirm_quiz":
                quiz = cmd.get("quiz") or []
                _ = run_confirm_quiz(quiz, collected=set(session.state.clues))
                continue

            if t == "show_end_screen":
                title = (cmd.get("title") or "").strip()
                narration = (cmd.get("narration") or "").strip()
                lesson = cmd.get("lesson") or []
                options = cmd.get("options") or []

                print(f"\n【{title}】")
                if narration:
                    print(narration)

                if isinstance(lesson, list) and lesson:
                    print("\n—")
                    print("【今天學到的】")
                    for ln in lesson[:6]:
                        if ln:
                            print(f"- {ln}")

                meta = cmd.get("meta") or {}
                rs = (meta.get("reason_summary") or "").strip()
                if rs:
                    print(f"理由整理：{rs}")
                if meta:
                    print("\n—")
                    print("【回顧卡片】")
                    if meta.get("accused"):
                        print(f"你當時偏向：{meta.get('accused')}")
                    obs = meta.get("selected_observations") or []
                    if obs:
                        print("你選的觀察：")
                        for x in obs[:6]:
                            print(f"- {x}")

                    lvl = meta.get("level")
                    if lvl:
                        score = meta.get("score")
                        th = meta.get("threshold")
                        s = (
                            f"{score}/{th}"
                            if isinstance(score, int) and isinstance(th, int) and th > 0
                            else ""
                        )
                        print(f"推理成熟度：{lvl} {s}".strip())

                    me = meta.get("matched_evidence") or []
                    if me:
                        print("有用到的線索：" + "、".join(me[:6]))

                    mk = meta.get("missing_key_evidence") or []
                    if mk:
                        print("可以再留意：" + "、".join(mk[:6]))

                print("\n你想怎麼做？")
                for i, opt in enumerate(options, start=1):
                    print(f"  {i}. {opt.get('text', '')}")

                raw = input("\n請選擇：").strip().lower()
                if not raw.isdigit():
                    print("輸入不正確喔～請輸入選項數字。")
                    continue

                idx = int(raw)
                if idx <= 0 or idx > len(options):
                    print("無效選項")
                    continue

                end_action = (options[idx - 1].get("id") or "").strip()
                res = session.step(PlayerAction(type="end_flow", end_action=end_action))

                for e in res.events:
                    print("\n" + e)

                # end_flow 很可能回 flow command，所以繼續 while 去吃
                break

            if t == "flow":
                on_flow((cmd.get("action") or "").strip())
                # ✅ 重要：flow 會換 session/case；不要再用舊 session 繼續處理
                return True

            if t == "show_reasoning_feedback":
                text = (cmd.get("text") or "").strip()
                meta = cmd.get("meta") or {}
                print("\n—")
                print("【推理回饋】（這不是判對錯，是幫你整理思路）")
                if text:
                    print(text)
                lvl = meta.get("level")
                if lvl:
                    score = meta.get("score")
                    th = meta.get("threshold")
                    s = (
                        f"{score}/{th}"
                        if isinstance(score, int) and isinstance(th, int) and th > 0
                        else ""
                    )
                    print(f"成熟度：{lvl} {s}".strip())

                me = meta.get("matched_evidence") or []
                if me:
                    print("你有用到的線索：" + "、".join(me[:6]))

                mk = meta.get("missing_key_evidence") or []
                if mk:
                    print("可以再留意：" + "、".join(mk[:6]))
                continue

        else:
            # 這輪 cmds 沒有 break（代表全部 continue 完，且沒有新的 res）
            # 直接跳出 while
            break

    return False


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
        nonlocal session, case_id, case, chosen_idx, config

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
            case_id = case_id2
            case = case2
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

        print(f"\n[WARN] Unknown flow action: {action}\n")

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
        if res is None:
            print("\n[BUG] session.step() 回傳 None（choose）")
            return

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

        did_flow = _handle_commands(session, res, on_flow=on_flow)
        if did_flow:
            chosen_idx = None
            continue

        if res.is_over:
            if not (res.commands or []):
                return
            continue
