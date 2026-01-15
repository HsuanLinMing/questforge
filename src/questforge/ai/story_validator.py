# src/questforge/ai/story_validator.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Optional

JsonMap = Dict[str, Any]


ALLOWED_NODE_FIELDS = {"title", "narration", "choices", "gain_clue", "lesson"}
ALLOWED_CHOICE_FIELDS = {"text", "next", "after"}

AUTO_CONTINUE_TEXT = {"繼續聽故事"}  # ✅ 建議統一，只收這個（最穩）

# 必備節點（模板骨架）
REQUIRED_NODE_IDS = {
    "start",
    "scene_01",
    "scene_02",
    "mid_reason",
    "scene_03",
    "scene_04",
    "final_accuse",
    "ending_result",
    "quit",
}

# 不該自動跳過的節點
INTERACTIVE_NODE_IDS = {"mid_reason", "final_accuse"}
ENDING_NODE_PREFIXES = ("ending", "quit")


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str]


def validate_story_nodes(story_nodes: JsonMap) -> ValidationResult:
    errors: List[str] = []

    if not isinstance(story_nodes, dict) or not story_nodes:
        return ValidationResult(False, ["STORY_NODES 必須是非空 dict"])

    # 1) 必備節點存在
    missing = sorted(list(REQUIRED_NODE_IDS - set(story_nodes.keys())))
    if missing:
        errors.append(f"缺少必備節點: {missing}")

    # 2) 每個節點欄位限制 + 型別檢查
    for node_id, node in story_nodes.items():
        if not isinstance(node_id, str) or not node_id.strip():
            errors.append("node id 必須是非空字串")
            continue
        if not isinstance(node, dict):
            errors.append(f"{node_id}: node 必須是 dict")
            continue

        extra_fields = set(node.keys()) - ALLOWED_NODE_FIELDS
        if extra_fields:
            errors.append(f"{node_id}: 出現不允許欄位 {sorted(list(extra_fields))}（只能用 {sorted(list(ALLOWED_NODE_FIELDS))}）")

        # required minimal fields
        title = node.get("title")
        narration = node.get("narration")
        choices = node.get("choices")

        if not isinstance(title, str) or not title.strip():
            errors.append(f"{node_id}: title 必須是非空字串")
        if not isinstance(narration, str) or not narration.strip():
            errors.append(f"{node_id}: narration 必須是非空字串")
        if not isinstance(choices, list):
            errors.append(f"{node_id}: choices 必須是 list")
            continue

        # lesson only recommended for ending_result but allow only list[str]
        if "lesson" in node:
            lesson = node.get("lesson")
            if not isinstance(lesson, list) or not all(isinstance(x, str) and x.strip() for x in lesson):
                errors.append(f"{node_id}: lesson 必須是 list[str] 且每項非空")

        # 3) choices item 欄位限制 + 型別檢查
        for i, c in enumerate(choices):
            if not isinstance(c, dict):
                errors.append(f"{node_id}: choices[{i}] 必須是 dict")
                continue
            extra_c = set(c.keys()) - ALLOWED_CHOICE_FIELDS
            if extra_c:
                errors.append(f"{node_id}: choices[{i}] 出現不允許欄位 {sorted(list(extra_c))}（只能用 {sorted(list(ALLOWED_CHOICE_FIELDS))}）")
            if not isinstance(c.get("text"), str) or not c["text"].strip():
                errors.append(f"{node_id}: choices[{i}].text 必須是非空字串")
            if not isinstance(c.get("next"), str) or not c["next"].strip():
                errors.append(f"{node_id}: choices[{i}].next 必須是非空字串")
            if "after" in c and (not isinstance(c["after"], str) or not c["after"].strip()):
                errors.append(f"{node_id}: choices[{i}].after 若存在必須是非空字串")

    # 4) 命名與互動節奏硬規則
    # - mid_reason：必須 3 個選項
    if "mid_reason" in story_nodes and isinstance(story_nodes["mid_reason"], dict):
        cs = story_nodes["mid_reason"].get("choices", [])
        if isinstance(cs, list) and len(cs) != 3:
            errors.append("mid_reason: choices 必須剛好 3 個（第1次互動）")

    # - final_accuse：必須 4 個選項（3嫌疑人+交給老師）
    if "final_accuse" in story_nodes and isinstance(story_nodes["final_accuse"], dict):
        cs = story_nodes["final_accuse"].get("choices", [])
        if isinstance(cs, list) and len(cs) != 4:
            errors.append("final_accuse: choices 必須剛好 4 個（3嫌疑人 + 我還不確定/交給老師）")

    # - ending_result：必須有 lesson 且 choices 只有 1
    if "ending_result" in story_nodes and isinstance(story_nodes["ending_result"], dict):
        node = story_nodes["ending_result"]
        if "lesson" not in node:
            errors.append("ending_result: 必須包含 lesson:list[str]")
        cs = node.get("choices", [])
        if isinstance(cs, list) and len(cs) != 1:
            errors.append("ending_result: choices 必須只有 1 個（結束故事）")

    # - quit：choices 必須是空 list
    if "quit" in story_nodes and isinstance(story_nodes["quit"], dict):
        cs = story_nodes["quit"].get("choices", [])
        if isinstance(cs, list) and len(cs) != 0:
            errors.append("quit: choices 必須為空（[]）")

    # 5) auto-continue 節點規則（非互動/非結局）
    for node_id, node in story_nodes.items():
        if not isinstance(node, dict):
            continue
        if node_id in INTERACTIVE_NODE_IDS:
            continue
        if node_id.startswith(ENDING_NODE_PREFIXES):
            continue

        # 視為「主線自動播放」節點的條件：scene_ 或 start
        if node_id == "start" or node_id.startswith("scene_"):
            cs = node.get("choices", [])
            if isinstance(cs, list):
                if len(cs) != 1:
                    errors.append(f"{node_id}: auto-continue 節點 choices 必須只有 1 個")
                else:
                    t = (cs[0].get("text") or "").strip()
                    if t not in AUTO_CONTINUE_TEXT:
                        errors.append(f"{node_id}: auto-continue 選項文字必須是 {sorted(list(AUTO_CONTINUE_TEXT))}，目前是「{t}」")

    # 6) next 指向必須存在（或允許 quit 結尾）
    node_ids = set(story_nodes.keys())
    for node_id, node in story_nodes.items():
        if not isinstance(node, dict):
            continue
        for i, c in enumerate(node.get("choices", []) or []):
            if not isinstance(c, dict):
                continue
            nxt = (c.get("next") or "").strip()
            if nxt and nxt not in node_ids:
                errors.append(f"{node_id}: choices[{i}].next 指向不存在節點「{nxt}」")

    ok = len(errors) == 0
    return ValidationResult(ok=ok, errors=errors)
