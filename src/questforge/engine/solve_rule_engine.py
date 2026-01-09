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

