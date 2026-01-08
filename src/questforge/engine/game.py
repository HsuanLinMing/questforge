from questforge.engine.case_selector import CaseSelector
from ..core.models import GameState
from ..content.cases import CASES


def show_status(state: GameState) -> None:
    """狀態列：選1 = 不顯示線索（只顯示回合/生命/金幣）"""
    p = state.player
    print("-" * 40)
    print(f"回合：{state.turn} | 生命：{p.hp}/{p.max_hp} | 金幣：{p.gold}")
    print("-" * 40)


def render_node(state: GameState, nodes: dict, node_id: str) -> None:
    """渲染節點：不印線索，但可在背景存 clue 供未來功能使用"""
    node = nodes[node_id]
    print(f"\n【{node.get('title', '')}】")
    print(node.get("narration", ""))

    # ✅ 選1：完全不顯示線索，但仍可默默收集（未來線索回放/TTS用）
    gain = node.get("gain_clue")
    if gain:
        state.player.clues.add(gain)

    # ✅ 若有 lesson（結尾教育段落），逐行印出
    lesson = node.get("lesson")
    if isinstance(lesson, list) and lesson:
        print("\n--- 小小學到的事 ---")
        for line in lesson:
            print(line)


def choose_next(nodes: dict, node_id: str) -> tuple[str, int]:
    """回傳 (next_node_id, choice_index[1-based])"""
    node = nodes[node_id]
    choices = node.get("choices", [])
    if not choices:
        return "quit", 0

    for idx, ch in enumerate(choices, start=1):
        print(f"{idx}) {ch['text']}")

    while True:
        s = input("> ").strip()
        if s.isdigit():
            i = int(s)
            if 1 <= i <= len(choices):
                return choices[i - 1]["next"], i
        print("輸入無效，請重新輸入。")


def game_loop() -> None:
    selector = CaseSelector(CASES)

    # 👉 一進來就隨機選案件（且避免重複，玩完一輪才重置）
    case = selector.pick()

    nodes = case["nodes"]
    current = case["start"]

    accuse_node = case["solve_rule"]["accuse_node"]
    correct_idx = case["solve_rule"]["correct_choice_index"]
    correct_next = case["solve_rule"]["correct_next"]
    wrong_next = case["solve_rule"]["wrong_next"]

    state = GameState()

    print("\n歡迎來到《QuestForge：菲菲＆樂樂小偵探》！")
    print(f"本次案件：{case['title']}\n")

    while True:
        state.turn += 1
        show_status(state)
        render_node(state, nodes, current)

        if current == "quit":
            return

        # ✅ 先讓玩家選
        next_id, chosen_idx = choose_next(nodes, current)

        # ✅ 再印出「選擇後的對話/觀察」（after）
        choices = nodes[current].get("choices", [])
        if 1 <= chosen_idx <= len(choices):
            after = choices[chosen_idx - 1].get("after")
            if after:
                print("\n" + after)

        # ✅ 最後指認節點：用 chosen_idx 判斷對錯（不看線索）
        if current == accuse_node:
            current = correct_next if chosen_idx == correct_idx else wrong_next
        else:
            current = next_id
