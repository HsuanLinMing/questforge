# src/questforge/contracts/story_nodes_validator_v1.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from questforge.contracts.story_nodes_v1 import StoryNodesPackage


@dataclass
class StoryNodesValidationError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


# ============================================================
# Basic validator rules for v1
# ============================================================

_REQUIRED_NODE_IDS = [
    "scene_01_start",
    "final_accuse",
    "scene_10_ending_clear",
    "scene_10_ending_nudge",
    "scene_10_ending_defer",
    "quit",
]

# ✅ 固定的不確定選項（合約一致）
UNSURE_CHOICE_TEXT = "我還不確定，交給大人"

# ✅ 開場禁詞：只保留會把開場直接拉成「破案 / 審訊」口氣的字
# 「不見 / 找不到」這類自然事件鋪陳不應該被 blocker 擋住
BANNED_OPENING_TERMS = [
    "開始調查",
    "推理",
    "真相",
    "嫌疑",
    "嫌疑人",
    "犯人",
    "兇手",
    "審問",
    "審訊",
    "解決案件",
    "破案",
]

# ✅ 舊版 22 段會把開場節奏綁得太死；現在放寬，讓後續 warmup / incident 有空間呼吸
_MIN_OPENING_PARAGRAPHS = 12


def _split_paragraphs(text: str) -> List[str]:
    return [x.strip() for x in (text or "").split("\n\n") if x.strip()]


def validate_story_nodes_v1(pkg: StoryNodesPackage) -> None:
    if pkg.meta.schema_version != "v1":
        raise StoryNodesValidationError(f"meta.schema_version 必須是 v1，現在是：{pkg.meta.schema_version}")

    # required node ids
    for nid in _REQUIRED_NODE_IDS:
        if nid not in pkg.nodes:
            raise StoryNodesValidationError(f"缺少必備節點：{nid}")

    # choices next and node next must exist
    for nid, node in pkg.nodes.items():
        if getattr(node, "next", None) and (node.next not in pkg.nodes):
            raise StoryNodesValidationError(f"[{nid}] next 指向不存在節點：{node.next}")
        for c in node.choices:
            if c.next and (c.next not in pkg.nodes):
                raise StoryNodesValidationError(f"[{nid}] choices.next 指向不存在節點：{c.next}")

    # final_accuse requirements
    fa = pkg.nodes.get("final_accuse")
    if not fa:
        raise StoryNodesValidationError("缺少 final_accuse")
    if len(fa.choices) != 4:
        raise StoryNodesValidationError("final_accuse.choices 必須是 4 個")
    if fa.choices[3].text != UNSURE_CHOICE_TEXT:
        raise StoryNodesValidationError(f"final_accuse 第4個 choice 必須完全等於：{UNSURE_CHOICE_TEXT}")
    if fa.solution_index is None or fa.solution_index not in (0, 1, 2):
        raise StoryNodesValidationError("final_accuse.solution_index 必須是 0/1/2")

    # opening requirements
    s1 = pkg.nodes.get("scene_01_start")
    if not s1:
        raise StoryNodesValidationError("缺少 scene_01_start")

    opening_text = "\n\n".join([it.text for it in s1.narration if (it.text or "").strip()])
    parts = _split_paragraphs(opening_text)
    if len(parts) < _MIN_OPENING_PARAGRAPHS:
        raise StoryNodesValidationError(f"scene_01_start.narration 至少 {_MIN_OPENING_PARAGRAPHS} 段，目前 {len(parts)} 段")

    for bad in BANNED_OPENING_TERMS:
        if bad and (bad in opening_text):
            raise StoryNodesValidationError(f"[scene_01_start] 出現禁止詞：{bad}")
