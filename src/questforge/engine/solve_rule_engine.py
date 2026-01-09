# src/questforge/engine/solve_rule_engine.py
from typing import Dict, Set, Tuple, List
from questforge.core.models import ReasoningFeedback

def score_suspect_support(suspect_support: Dict[str, int], clues: Set[str]) -> Tuple[int, List[str], List[str]]:
    score = 0
    matched, missing = [], []
    for key, pts in (suspect_support or {}).items():
        if key in clues:
            score += int(pts)
            matched.append(key)
        else:
            missing.append(key)
    return score, matched, missing

def reasoning_level(score: int, threshold: int) -> str:
    if threshold <= 0:
        # 沒設定門檻時：用分數做簡單分級
        if score >= 2:
            return "good"
        if score >= 1:
            return "ok"
        return "weak"
    if score >= threshold:
        return "good"
    if score >= max(1, threshold // 2):
        return "ok"
    return "weak"

def handle_ending_check(*, solve_rule: dict, target: str, clues: Set[str]) -> ReasoningFeedback:
    threshold = int(solve_rule.get("threshold", 0))
    suspects = solve_rule.get("suspects") or {}

    support = ((suspects.get(target) or {}).get("support")) or {}
    score, matched, missing = score_suspect_support(support, clues)
    level = reasoning_level(score, threshold)

    if level == "good":
        msg = "霏霏：你的推理很有根據！你抓到好幾個重要的小細節。"
    elif level == "ok":
        msg = "霏霏：你的想法有一些線索支持喔！如果再多注意一個關鍵點，你會更有把握。"
    else:
        msg = "霏霏：你願意說出你的想法很棒！我們可以再觀察一下，找更明確的線索。"

    return ReasoningFeedback(
        score=score,
        level=level,  # type: ignore
        matched_evidence=matched,
        missing_key_evidence=missing,
        message=msg,
    )
