from typing import Any, Dict, List


def run_quiz(quiz: List[Dict[str, Any]]) -> bool:
    """在指認時跑推理小測驗。全部答對才算成功。"""
    for i, item in enumerate(quiz, start=1):
        q = item.get("q", "")
        options = item.get("options", [])
        ans = int(item.get("answer_index", -1))

        print(f"\n🧩 推理題 {i}：{q}")
        for idx, opt in enumerate(options, start=1):
            print(f"  {idx}. {opt}")

        chosen = _ask_choice(len(options))
        if chosen != ans:
            wrong = item.get("explain_wrong")
            if wrong:
                print("\n" + wrong)
            return False

        right = item.get("explain_right")
        if right:
            print("\n" + right)

    return True


def _ask_choice(n: int) -> int:
    while True:
        raw = input("你的答案：").strip().lower()
        if raw == "q":
            return -999  # 你也可以選擇在這裡退出
        if raw.isdigit():
            x = int(raw)
            if 1 <= x <= n:
                return x
        print("請輸入選項數字。")
