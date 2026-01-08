from __future__ import annotations
from typing import List, Dict, Set, Any


def _pick_index(max_n: int, can_skip: bool) -> int | None:
    """回傳 0-based index；若跳過回傳 None"""
    while True:
        raw = input("\n請選擇（輸入數字{}）：".format("，或 S=跳過" if can_skip else "")).strip().lower()
        if can_skip and raw in ("s", "skip"):
            return None
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= max_n:
                return idx - 1
        print("輸入不正確喔～請輸入選項數字{}".format("，或 S 跳過" if can_skip else ""))


def run_confirm_quiz(
    quiz: List[Dict[str, Any]],
    collected: Set[str],
    can_skip: bool = True,
) -> List[str]:
    """偵探回顧（方案C）
    - 不計分、不對錯：只是讓孩子回顧「我靠什麼想到的」
    - 可跳過：避免像考試
    - 會回傳玩家挑到的線索 key 清單（可記到 notes 或 vars）
    """
    if not quiz:
        return []

    print("\n📝 偵探回顧（可跳過）")
    print("霏霏：這不是考試喔～只是回想一下，你剛剛靠哪個小細節想到的。")

    picked: List[str] = []

    for item in quiz:
        q = (item.get("q") or "").strip()
        options = item.get("options") or []
        labels = item.get("labels") or []
        after = (item.get("after") or "").strip()

        if not q or not options:
            continue

        print("\n" + q)

        # 顯示選項：優先顯示 label，並標示是否「你有看到/收集到」
        for i, key in enumerate(options, start=1):
            label = labels[i - 1] if i - 1 < len(labels) else str(key)
            has = "✅" if str(key) in collected else "▫️"
            print(f"  {i}. {label}  {has}")

        idx0 = _pick_index(len(options), can_skip=can_skip)
        if idx0 is None:
            print("樂樂：好～我們先跳過，直接進故事結尾！")
            continue

        chosen_key = str(options[idx0])
        picked.append(chosen_key)

        # 不判斷對錯，只給回饋
        if after:
            print("\n" + after)
        else:
            print("\n霏霏：很好～把『看到的』說出來，推理就會更清楚。")

    return picked
