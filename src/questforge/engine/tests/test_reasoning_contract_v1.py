from __future__ import annotations

from questforge.content.cases import CASES
from questforge.core.models import DetectiveState, GameConfig
from questforge.engine.session import GameSession


def test_end_screen_meta_has_contract_v1():
    case = CASES["2"]
    s = GameSession(
        state=DetectiveState(),
        nodes=case["nodes"],
        start_node=case["start"],
        config=GameConfig(),
        solve_rule=case.get("solve_rule", {}) or {},
    )

    # 直接跳到一個 end_screen node（依你的 case2 節點實際存在的 tag）
    # 這裡用保守方式：找第一個 tag in ("ending_result","ending_wrong","epilogue")
    target = None
    for node_id, node in case["nodes"].items():
        if (node.get("tag") or "").strip() in ("ending_result", "ending_wrong", "epilogue"):
            target = node_id
            break
    assert target is not None, "Case 2 must have an end screen node"

    cmd = s._make_end_screen_command(node_id=target)  # noqa: SLF001
    meta = cmd.get("meta") or {}
    assert meta.get("version") == "reasoning_contract_v1"

    # 核心欄位一定要存在（哪怕是空）
    required = [
        "version","case_title","node_id","tag","turn",
        "accused","reason_mode","reason_ids","selected_observations","reason_text","reason_summary",
        "clues_preview","level","score","threshold","engine_message","matched_evidence","missing_key_evidence"
    ]
    for k in required:
        assert k in meta, f"missing key: {k}"
