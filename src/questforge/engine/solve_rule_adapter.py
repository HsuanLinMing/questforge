from typing import Dict, Any, List
from questforge.core.models import AccuseConfig, AccuseReasonOption


def solve_rule_to_accuse_config(solve_rule: Dict[str, Any]) -> AccuseConfig:
    """
    把 story solve_rule(dict) 轉成 AccuseConfig（Day9 統一入口）
    """

    suspects = list(solve_rule.get("suspects", {}).keys())

    # reason_options（A：選項）
    reasons: List[AccuseReasonOption] = []
    for r in solve_rule.get("reason_options", []) or []:
        rid = (r.get("id") or "").strip()
        if not rid:
            continue

        reasons.append(
            AccuseReasonOption(
                reason_id=rid,
                text=(r.get("text") or "").strip(),
                expected_evidence=list(r.get("expected_evidence") or []),
                base_score=int(r.get("base_score", 0) or 0),
            )
        )

    # 關鍵證據權重（可選）
    key_evidence = solve_rule.get("key_evidence", {}) or {}

    # good 門檻
    min_good_score = int(
        solve_rule.get("min_good_score")
        or solve_rule.get("threshold")
        or 6
    )

    truth = (solve_rule.get("correct_suspect") or "").strip() or None

    return AccuseConfig(
        suspects=suspects,
        reasons=reasons,
        truth=truth,
        key_evidence=dict(key_evidence),
        min_good_score=min_good_score,
    )
