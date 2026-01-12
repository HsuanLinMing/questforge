from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple, Optional, List

from questforge.ai.ai_client import build_ai_client
from questforge.ai.schemas import ResponseRequest
from questforge.cli.cli_menus import show_clues_menu, show_notes_menu, show_saves_list
from questforge.core.models import GameConfig
from questforge.engine.session import GameSession
from questforge.engine.actions import PlayerAction
from questforge.engine.save_manager import SaveManager


def dev_test_ai_flow():
    ai = build_ai_client()
    story = ai.generate_story()
    print("== TITLE ==")
    print(story.title)
    print("\n== PROLOGUE ==")
    print(story.prologue)

    print("\n== SCENES ==")
    for sc in story.scenes:
        print(f"\n[{sc.title}]")
        print(sc.narration)
        for ob in sc.observations:
            print(f"- {ob.text}")

    print("\n== COOLDOWN ==")
    print(story.cooldown_dialogue)

    print("\n== TEACHER ==")
    print(story.teacher_scene)

    print("\n== END ==")
    print(story.open_ending)

    resp = ai.generate_response(
        ResponseRequest(
            intent="support_uncertain", role="feifei", player_text="我不確定"
        )
    )
    print("\n== RESPONSE ==")
    print(resp.text)


def handle_cli_command(
    raw: str,
    *,
    save_mgr: SaveManager,
    session: GameSession,
    case_id: str,
    case: Dict,
    config: GameConfig,
    chosen_idx_ref: Dict[str, Optional[int]],
) -> Tuple[bool, Optional[GameSession], str, Dict, GameConfig]:
    """
    回傳：
      handled: 是否已處理（True 代表主迴圈應 continue / return）
      new_session: 若為 None 代表要結束遊戲（例如 q）
      case_id/case/config: 可能因 load 而改變
    """
    # quit
    if raw == "q":
        # 離開前 autosave（容錯）
        try:
            save_mgr.save_autosave(
                session=session,
                case_id=case_id,
                case_title=case.get("title", ""),
                config=config,
            )
        except Exception:
            pass
        _ = session.step(PlayerAction(type="quit"))
        return True, None, case_id, case, config

    # replay
    if raw == "r":
        chosen_idx_ref["value"] = None
        res = session.step(PlayerAction(type="replay"))
        for e in res.events:
            print(f"\n{e}")
        return True, session, case_id, case, config

    # clues
    if raw == "c":
        show_clues_menu(session.state)

        # Day13: AI transition back to story
        resp = session.say_once(
            ResponseRequest(
                intent="back_from_clues",
                role="feifei",
                scene_title=(
                    session.nodes.get(session.current, {}).get("title") or ""
                ).strip(),
                node_id=session.current,
                turn=session.state.turn,
                clues_preview=[
                    session.state.clue_labels.get(k, k)
                    for k in sorted(session.state.clues)
                ][:6],
            )
        )
        print("\n" + resp.text)
        return True, session, case_id, case, config

    # notes
    if raw == "n":
        show_notes_menu(session.state)

        # Day13: AI transition back to story
        resp = session.say_once(
            ResponseRequest(
                intent="back_from_notes",
                role="feifei",
                scene_title=(
                    session.nodes.get(session.current, {}).get("title") or ""
                ).strip(),
                node_id=session.current,
                turn=session.state.turn,
                clues_preview=[
                    session.state.clue_labels.get(k, k)
                    for k in sorted(session.state.clues)
                ][:6],
            )
        )
        print("\n" + resp.text)
        return True, session, case_id, case, config

    # saves list
    if raw == "p":
        show_saves_list(save_mgr)
        input("按 Enter 回到故事…")

        resp = session.say_once(
            ResponseRequest(
                intent="back_from_saves",
                role="feifei",
                scene_title=(
                    session.nodes.get(session.current, {}).get("title") or ""
                ).strip(),
                node_id=session.current,
                turn=session.state.turn,
                clues_preview=[
                    session.state.clue_labels.get(k, k)
                    for k in sorted(session.state.clues)
                ][:6],
            )
        )
        print("\n" + resp.text)
        return True, session, case_id, case, config

    # save
    if raw == "s":
        try:
            target = save_mgr.prompt_save_target_path()
            save_mgr.save_to_path(
                target,
                session=session,
                case_id=case_id,
                case_title=case.get("title", ""),
                config=config,
            )
            print(f"\n[存檔成功] 已儲存到 {Path(target).name}")
        except Exception as e:
            print(f"\n[存檔失敗] {e}")
        return True, session, case_id, case, config

    # load
    if raw == "l":
        try:
            src = save_mgr.prompt_load_source_path()
            if not src:
                return True, session, case_id, case, config

            new_session, new_case_id, new_case, new_config = save_mgr.load_from_file(
                src
            )
            chosen_idx_ref["value"] = None

            print(
                f"\n[讀檔成功] 已還原：{new_case.get('title','')}（來源：{Path(src).name}，enable_quiz={new_config.enable_quiz}）"
            )
            return True, new_session, new_case_id, new_case, new_config
        except Exception as e:
            print(f"\n[讀檔失敗] {e}")
            return True, session, case_id, case, config

    return False, session, case_id, case, config


def _parse_multi_indexes(raw: str) -> List[int]:
    s = (raw or "").strip()
    if not s:
        return []

    for ch in ["，", ",", ";", "；", "、"]:
        s = s.replace(ch, " ")

    parts = [p for p in s.split() if p]
    idxs: List[int] = []

    for p in parts:
        if not p.isdigit():
            return [-1]
        idxs.append(int(p))

    return idxs


def cli_handle_ask_reason(command: Dict[str, Any]) -> PlayerAction:
    options = command.get("options") or []

    print("\n【你為什麼這樣想？選出你的線索】")
    for i, opt in enumerate(options, start=1):
        print(f"{i}. {(opt.get('text') or '').strip()}")

    unsure_index = len(options) + 1
    print(f"{unsure_index}. 我說不太清楚（先交給老師）")

    raw = input("請選擇理由（可多選，如：1 2）：").strip()
    idxs = _parse_multi_indexes(raw)

    if idxs == [-1] or any(i <= 0 or i > unsure_index for i in idxs):
        print("輸入不正確，先幫你選『我說不太清楚』。")
        return PlayerAction(type="set_reasons", reason_ids=[])

    if not idxs or unsure_index in idxs:
        return PlayerAction(type="set_reasons", reason_ids=[])

    reason_ids: List[str] = []
    seen = set()
    for i in idxs:
        if i in seen:
            continue
        seen.add(i)
        rid = (options[i - 1].get("id") or "").strip()
        if rid:
            reason_ids.append(rid)

    return PlayerAction(type="set_reasons", reason_ids=reason_ids)

def cli_handle_ask_reason_text(command: Dict[str, Any]) -> PlayerAction:
    print("\n【你為什麼這樣想？用一句話說說看】")
    print("提示：只要講『你看到的』就好，不用猜誰做的。")
    raw = input("你想說：").strip()

    # 空字串就當不確定
    if not raw:
        return PlayerAction(type="set_reasons", reason_ids=[], reason_text="")

    # 限制一下長度（避免太長）
    raw = raw[:80]
    return PlayerAction(type="set_reasons", reason_ids=[], reason_text=raw)
