from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

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
    """CLI：印出存檔列表（用 SaveManager.list() 取得資料）。"""
    saves = save_mgr.list()  # ✅ 這個方法你已經有了（回 List[SaveMeta]）

    print("\n" + "=" * 40)
    print("【存檔列表】")
    if not saves:
        print("（目前沒有任何存檔）")
    else:
        for i, m in enumerate(saves, start=1):
            if m.broken:
                print(f"{i}. {m.file}  [壞檔/無法解析]")
                continue
            title = m.case_title or "（未知案件）"
            saved_at = m.saved_at or "-"
            quiz = "ON" if m.enable_quiz else "OFF"
            print(f"{i}. {m.file} | {title} | 回合 {m.turn} | quiz {quiz} | {saved_at}")
    print("=" * 40)



def ask_reason_text(
    prompt_title: str = "【你為什麼這樣想？】",
) -> Tuple[List[str], str]:
    """
    text-mode：讓玩家輸入一句話理由
    回傳：(reason_ids, reason_text)
      - reason_ids 固定 []
      - reason_text 為玩家輸入（可空，但通常會再提示一次）
    """
    print(prompt_title)
    print("請用一句話說說你的理由（直接按 Enter 送出）")
    text = input("理由：").strip()

    # 允許空白，但給一次溫和提醒
    if not text:
        print("（沒關係，你也可以先寫很短的一句，例如：『我覺得怪怪的』）")
        text = input("理由：").strip()

    return [], text


def ask_reason_choice_multi(
    options: List[Dict[str, Any]], title: str
) -> Tuple[List[str], str]:
    """
    choice-mode：多選理由（你現有的邏輯可以替換掉這段）
    options: [{ "id": "1", "text": "..." }, ...] 或 { "id": ..., "label"/"text": ... }
    回傳：(reason_ids, reason_text) -> reason_text 固定 ""
    """
    print(title)
    for i, opt in enumerate(options, start=1):
        label = str(opt.get("text") or opt.get("label") or opt.get("title") or "")
        print(f"{i}. {label}")

    print("（可多選：用逗號分隔，例如 1,3；或輸入 0 表示『我不太清楚』）")
    raw = input("請選擇理由：").strip()

    if raw == "0":
        return [], ""  # 由引擎用「不確定」選項處理也可；這裡先回空

    picks: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            picks.append(int(part))

    reason_ids: List[str] = []
    for p in picks:
        idx = p - 1
        if 0 <= idx < len(options):
            rid = options[idx].get("id")
            if rid is None:
                # 若沒 id，就用序號字串當 id（至少可追蹤）
                rid = str(p)
            reason_ids.append(str(rid))

    # 去重但保序
    seen = set()
    out: List[str] = []
    for r in reason_ids:
        if r in seen:
            continue
        seen.add(r)
        out.append(r)

    return out, ""
