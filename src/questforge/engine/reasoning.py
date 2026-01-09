from __future__ import annotations

from typing import Set, List
from questforge.core.models import AccuseConfig, AccuseResult, ReasoningFeedback


from typing import List, Set
from questforge.core.models import AccuseConfig, AccuseResult, ReasoningFeedback

def evaluate_accuse(
    config: AccuseConfig,
    result: AccuseResult,
    clues: Set[str],
) -> ReasoningFeedback:
    reason_ids = result.normalized_reason_ids()

    # 建立 reason_id -> option 的索引（相容 id / reason_id）
    opt_map = {}
    for opt in (config.reasons or []):
        rid = (getattr(opt, "reason_id", "") or "").strip()
        if rid:
            opt_map[rid] = opt

    matched: List[str] = []
    missing: List[str] = []
    score = 0

    # 1) 多理由：每個理由給 base_score + 其 expected_evidence 命中加權
    for rid in reason_ids:
        opt = opt_map.get(rid)
        if not opt:
            continue

        # base_score：避免孩子全空（你原本就有這理念）
        score += int(getattr(opt, "base_score", 0) or 0)

        expected = [str(x) for x in (getattr(opt, "expected_evidence", []) or []) if x]
        for ev in expected:
            if ev in clues:
                score += int(config.key_evidence.get(ev, 1) or 1)  # 沒配置就給 1
                matched.append(ev)
            else:
                missing.append(ev)

    # 2) 額外：若孩子沒選理由，也不判錯，只給引導
    if not reason_ids:
        return ReasoningFeedback(
            score=0,
            level="weak",
            matched_evidence=[],
            missing_key_evidence=[],
            message="你願意先停一下很棒！如果不確定，把看到的交給老師最安全。",
        )

    # 去重但保序
    def uniq(xs: List[str]) -> List[str]:
        seen = set()
        out = []
        for x in xs:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    matched = uniq(matched)
    missing = uniq(missing)

    # 3) 成熟度判斷：沿用 config.min_good_score
    good = int(getattr(config, "min_good_score", 6) or 6)
    ok = max(1, good // 2)

    if score >= good:
        level = "good"
        msg = "你的推理很有根據！你是用線索在想，不是在亂猜。"
    elif score >= ok:
        level = "ok"
        msg = "你的想法有一些根據喔！如果再找到一兩個小細節會更有把握。"
    else:
        level = "weak"
        msg = "你願意整理想法很棒！我們可以再觀察一下，找更明確的線索。"

    return ReasoningFeedback(
        score=score,
        level=level,
        matched_evidence=matched,
        missing_key_evidence=missing,
        message=msg,
    )

def score_reasons_with_evidence(
    *,
    reason_ids: list[str],
    reason_options: list[dict],
    clues: set[str],
    support_map: dict[str, int],
) -> tuple[int, list[str], list[str]]:
    """
    回傳：
    - total_score
    - matched_evidence
    - missing_evidence
    """

    total = 0
    matched: set[str] = set()
    missing: set[str] = set()

    opt_map = {o.get("id"): o for o in reason_options}

    for rid in reason_ids:
        opt = opt_map.get(rid)
        if not opt:
            continue

        # 1️⃣ base score
        total += int(opt.get("base_score", 0) or 0)

        # 2️⃣ expected evidence
        for ev in opt.get("expected_evidence", []):
            if ev in clues:
                matched.add(ev)
                total += int(support_map.get(ev, 0) or 0)
            else:
                missing.add(ev)

    return total, sorted(matched), sorted(missing)
