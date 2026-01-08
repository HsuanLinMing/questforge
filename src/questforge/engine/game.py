from typing import Tuple, Dict, Any
from questforge.engine.case_selector import CaseSelector
from questforge.engine.confirm_quiz import run_confirm_quiz
from ..core.models import DetectiveState, GameConfig
from ..content.cases import CASES
from questforge.engine.session import GameSession
from questforge.engine.actions import PlayerAction


def show_status(state: DetectiveState) -> None:
    if state.clues:
        # 依 label 顯示（fallback key）
        readable = []
        for k in sorted(state.clues):
            readable.append(state.clue_labels.get(k, k))
        clues = "、".join(readable)
    else:
        clues = "（還沒有）"

    flags = "、".join(sorted(state.flags)) if state.flags else "（無）"
    print("-" * 40)
    print(f"回合：{state.turn}")
    print(f"線索：{clues}")
    print(f"旗標：{flags}")
    print("-" * 40)


def render_node(state, nodes: dict, node_id: str) -> None:
    node = nodes[node_id]
    print(f"\n【{node.get('title', '')}】")
    print(node.get("narration", ""))

    choices = node.get("choices", [])
    if choices:
        print("\n你想怎麼做？")
        for i, c in enumerate(choices, start=1):
            print(f"  {i}. {c.get('text', '')}")
        print("\n（輸入數字選擇，R=重播本段，Q=離開）")


def choose_next(nodes: Dict[str, Any], current: str) -> Tuple[str, int]:
    """讓玩家選下一步（純故事版）
    - 輸入數字：選選項
    - 輸入 R：重播本段（回傳 current, 0）
    - 輸入 Q：離開（回傳 'quit', 0）
    """
    choices = nodes[current].get("choices", [])

    # 沒有選項就直接結束（或你也可以設計成自動 next）
    if not choices:
        return "quit", 0

    while True:
        raw = input("\n請選擇（輸入數字，R=重播，Q=離開）：").strip().lower()

        if raw == "q":
            return "quit", 0

        if raw == "r":
            return current, 0  # 交給 game_loop 決定「留在原地重播」

        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(choices):
                return choices[idx - 1].get("next", "quit"), idx

        print("輸入不正確喔～請輸入選項數字，或 R / Q。")


def trace(
    state: DetectiveState, case_title: str, current: str, chosen_idx: int | None = None
) -> None:
    clues = ",".join(sorted(state.clues)) if state.clues else "-"
    pick = f" choice={chosen_idx}" if chosen_idx is not None else ""
    print(
        f"[TRACE] turn={state.turn} case={case_title} node={current}{pick} clues={clues}"
    )


def score_suspect(state: DetectiveState, rule: dict, suspect: str) -> int:
    suspects = rule.get("suspects", {})
    profile = suspects.get(suspect, {})
    support = profile.get("support", {})

    score = 0
    for ev in state.clues:
        score += support.get(ev, 0)

    return score


def is_reasonable_accuse(
    state: DetectiveState, case: dict, chosen_suspect: str
) -> bool:
    rule = case.get("solve_rule", {})
    threshold = rule.get("threshold", 0)
    score = score_suspect(state, rule, chosen_suspect)

    return score >= threshold


def collect_evidence_from_choice(state: DetectiveState, choice: dict) -> None:
    evs = choice.get("evidence", []) or []

    for ev in evs:
        if not ev:
            continue

        # ✅ 方案 C：支援 dict 格式 {key,label}
        if isinstance(ev, dict):
            key = str(ev.get("key", "")).strip()
            label = ev.get("label")
            state.add_clue_with_label(key, label)
            continue

        # ✅ 向下相容：如果你以前 evidence 是字串（直接當 key 存）
        if isinstance(ev, str):
            state.add_clue_with_label(ev, None)
            continue

        # ✅ 其他型別保守處理（不建議，但不讓它炸）
        state.add_clue_with_label(str(ev), None)


from questforge.engine.case_selector import CaseSelector
from questforge.engine.confirm_quiz import run_confirm_quiz
from ..core.models import DetectiveState, GameConfig
from ..content.cases import CASES
from typing import Tuple, Dict, Any


def game_loop(config: GameConfig | None = None) -> None:
    selector = CaseSelector(CASES)
    config = config or GameConfig()

    case = selector.pick()
    nodes = case["nodes"]
    current = case["start"]

    rule = case.get("solve_rule", {})
    accuse_node = rule.get("accuse_node", "")
    correct_next = rule.get("correct_next", "quit")
    wrong_next = rule.get("wrong_next", "quit")
    correct_suspect = rule.get("correct_suspect")  # e.g. 'dongdong'

    state = DetectiveState()

    print("\n歡迎來到《QuestForge：霏霏＆樂樂小偵探》！")
    print(f"本次案件：{case['title']}\n")

    while True:
        state.turn += 1
        trace(state, case["title"], current)
        show_status(state)
        render_node(state, nodes, current)

        if current == "quit":
            return

        next_id, chosen_idx = choose_next(nodes, current)

        if next_id == current and chosen_idx == 0:  # R 重播
            continue

        # after + evidence
        choices = nodes[current].get("choices", [])
        choice = None
        if 1 <= chosen_idx <= len(choices):
            choice = choices[chosen_idx - 1]
            after = choice.get("after")
            print(
                "\n" + after
                if after
                else "\n霏霏：嗯…我們再想想，這個選擇一定有它的意思。"
            )
            collect_evidence_from_choice(state, choice)

        trace(state, case["title"], current, chosen_idx)

        # ✅ Day5：推理指認（門檻分數）+ 可選「回顧題」

        if current == accuse_node:
            # next_id 可能是 accuse_dongdong / accuse_mei / accuse_ali / ending_check
            if next_id.startswith("accuse_"):
                chosen_suspect = next_id.replace("accuse_", "")

                reasonable = is_reasonable_accuse(state, case, chosen_suspect)

                if reasonable:
                    print(
                        "\n霏霏：嗯…你的想法很有根據，我們把『看到的』整理好，交給老師最安全。"
                    )
                    confirm = rule.get("confirm_quiz", [])
                    if config.enable_quiz and confirm:
                        run_confirm_quiz(
                            quiz=confirm,
                            collected=set(state.clues),
                            can_skip=config.quiz_can_skip,
                        )
                else:
                    print(
                        "\n樂樂：我覺得你可能快想到了，但我們好像還少一個確認點。先找老師一起處理！"
                    )

                current = "ending_check"  # ⭐ 模式1：永遠交給老師接手
            else:
                # 玩家選「不確定，交給老師」→ 直接走下個節點
                current = next_id
        else:
            current = next_id


def game_loop_v6(config: GameConfig | None = None) -> None:
    """Day6：改用 GameSession（純邏輯核心），CLI 只是 adapter。"""
    selector = CaseSelector(CASES)
    config = config or GameConfig()

    case = selector.pick()
    nodes = case["nodes"]
    rule = case.get("solve_rule", {})
    accuse_node = rule.get("accuse_node", "")

    state = DetectiveState()
    session = GameSession(
        state=state, nodes=nodes, start_node=case["start"], config=config
    )

    print("\n歡迎來到《QuestForge：霏霏＆樂樂小偵探》！")
    print(f"本次案件：{case['title']}\n")

    while True:
        # 先拿 view（避免 current 指到不存在的節點時 print 掛掉）
        view = session.get_view()
        if view is None:
            return

        state.turn += 1
        current = session.current
        trace(state, case["title"], current)
        show_status(state)

        print(f"\n【{view.title}】")
        print(view.narration)

        if view.choices:
            print("\n你想怎麼做？")
            for c in view.choices:
                print(f"  {c.index}. {c.text}")
            print("\n（輸入數字選擇，R=重播本段，Q=離開）")
        else:
            _ = session.step(PlayerAction(type="quit"))
            return

        raw = input("\n請選擇（輸入數字，R=重播，Q=離開）：").strip().lower()

        if raw == "q":
            _ = session.step(PlayerAction(type="quit"))
            return

        if raw == "r":
            res = session.step(PlayerAction(type="replay"))
            for e in res.events:
                print(f"\n{e}")
            continue

        if not raw.isdigit():
            print("輸入不正確喔～請輸入選項數字，或 R / Q。")
            continue

        idx = int(raw)
        if idx <= 0 or idx > len(view.choices):
            print("輸入不正確喔～請輸入有效的選項數字。")
            continue

        prev_node = session.current
        res = session.step(PlayerAction(type="choose", choice_index=idx))
        for e in res.events:
            print("\n" + e)

        # ✅ Day5：指認 accuse_node 邏輯保留在 CLI adapter
        if prev_node == accuse_node:
            next_id = res.selected_next or ""
            if next_id.startswith("accuse_"):
                chosen_suspect = next_id.replace("accuse_", "")
                reasonable = is_reasonable_accuse(state, case, chosen_suspect)

                if reasonable:
                    print(
                        "\n霏霏：嗯…你的想法很有根據，我們把『看到的』整理好，交給老師最安全。"
                    )
                    confirm = rule.get("confirm_quiz", [])
                    if config.enable_quiz and confirm:
                        run_confirm_quiz(
                            quiz=confirm,
                            collected=set(state.clues),
                            can_skip=config.quiz_can_skip,
                        )
                else:
                    print(
                        "\n樂樂：我覺得你可能快想到了，但我們好像還少一個確認點。先找老師一起處理！"
                    )

                # ⭐ 模式1：永遠交給老師接手
                session.current = "ending_check"

        if res.is_over:
            return
