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
