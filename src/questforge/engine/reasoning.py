from __future__ import annotations

from typing import Set, List
from questforge.core.models import AccuseConfig, AccuseResult, ReasoningFeedback


def evaluate_accuse(config: AccuseConfig, result: AccuseResult, clues: Set[str]) -> ReasoningFeedback:
    """依據玩家線索 + 選擇的理由，算推理成熟度（不做卡關）。"""

    # 1) 找到理由選項
    reason = next((r for r in config.reasons if r.reason_id == result.reason_id), None)

    score = 0
    matched: List[str] = []
    missing_key: List[str] = []

    # 2) base score（理由本身給點分，避免孩子卡死）
    if reason is not None:
        score += int(reason.base_score or 0)

    # 3) 關鍵證據加權（你 state.clues 裡有的就加分）
    for ev, pts in (config.key_evidence or {}).items():
        if ev in clues:
            score += int(pts)
            matched.append(ev)
        else:
            # 關鍵證據缺失，用來給提示（不是卡關）
            if int(pts) >= 2:
                missing_key.append(ev)

    # 4) 理由對應證據：如果選的理由期待某些線索，命中就再加一點
    if reason is not None:
        for ev in reason.expected_evidence:
            if ev in clues:
                score += 1
                if ev not in matched:
                    matched.append(ev)

    # 5) 分級（可調整）
    if score >= config.min_good_score:
        level = "good"
    elif score >= max(1, config.min_good_score // 2):
        level = "ok"
    else:
        level = "weak"

    # 6) 產生孩子友善的回饋文案
    if level == "good":
        msg = "你的推理很成熟！你有注意到幾個重要的線索，判斷很有根據。"
    elif level == "ok":
        msg = "你的想法有一些根據喔！如果能再找到一兩個關鍵線索，你會更有把握。"
    else:
        msg = "你願意說出你的想法很棒！我們可以再觀察一下，找找更明確的線索。"

    return ReasoningFeedback(
        score=score,
        level=level,
        matched_evidence=matched,
        missing_key_evidence=missing_key,
        message=msg,
    )
