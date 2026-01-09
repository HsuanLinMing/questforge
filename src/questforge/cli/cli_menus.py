from __future__ import annotations

from typing import Optional

from questforge.core.models import DetectiveState
from questforge.engine.save_manager import SaveManager


def show_clues_menu(state: DetectiveState) -> None:
    """CLI：線索清單（用中文 label 顯示）。"""
    print("\n" + "=" * 40)
    print("【線索清單】")
    if not state.clues:
        print("（目前還沒有線索）")
    else:
        for i, k in enumerate(sorted(state.clues), start=1):
            label = state.clue_labels.get(k, k)
            print(f"{i}. {label}  ({k})")
    print("=" * 40)
    input("按 Enter 回到故事…")


def show_notes_menu(state: DetectiveState) -> None:
    """CLI：偵探筆記清單（保留順序）。"""
    print("\n" + "=" * 40)
    print("【偵探筆記】")
    if not state.notes:
        print("（目前還沒有筆記）")
    else:
        for i, note in enumerate(state.notes, start=1):
            print(f"{i}. {note}")
    print("=" * 40)
    input("按 Enter 回到故事…")


def show_saves_list(save_mgr: SaveManager) -> None:
    """CLI：印出存檔列表（用 SaveManager 取得資料）。"""
    saves = save_mgr.list_saves()
    print("\n" + "=" * 40)
    print("【存檔列表】")
    if not saves:
        print("（目前沒有任何存檔）")
    else:
        for i, m in enumerate(saves, start=1):
            if m.get("broken"):
                print(f"{i}. {m['file']}  [壞檔/無法解析]")
                continue
            title = m.get("case_title") or "（未知案件）"
            turn = m.get("turn", 0)
            saved_at = m.get("saved_at") or "-"
            quiz = "ON" if m.get("enable_quiz") else "OFF"
            print(f"{i}. {m['file']} | {title} | 回合 {turn} | quiz {quiz} | {saved_at}")
    print("=" * 40)
