# src/questforge/adapters/story_nodes_to_session.py
from __future__ import annotations

from typing import Dict, Tuple

from questforge.contracts.story_nodes_v1 import (
    StoryNodesPackage,
    StoryNode,
    NarrationItem,
    ChoiceItem,
)
from questforge.contracts.story_nodes_validator_v1 import (
    validate_story_nodes_v1,
)

from questforge.engine.session import GameSession
from questforge.core.models import DetectiveState, GameConfig


# ======================================================
# Public API
# ======================================================


def build_game_session_from_story_nodes(
    *,
    pkg: StoryNodesPackage,
    seed: int | None = None,
) -> Tuple[GameSession, Dict]:
    """
    STORY_NODES (v1) → GameSession

    - 先 validate
    - 再轉成 engine nodes
    - 最後組裝 GameSession
    """

    # 1️⃣ validate（擋爛輸出）
    validate_story_nodes_v1(pkg)

    # 2️⃣ nodes 轉換
    engine_nodes = _build_engine_nodes(pkg)

    # 3️⃣ solve_rule（由系統補，不由故事決定）
    solve_rule = _build_solve_rule()

    # 4️⃣ GameConfig / State
    cfg = GameConfig(seed=seed) if seed is not None else GameConfig()
    state = DetectiveState()

    session = GameSession(
        state=state,
        nodes=engine_nodes,
        start_node="scene_01_start",
        config=cfg,
        solve_rule=solve_rule,
    )

    return session, solve_rule


# ======================================================
# Engine nodes
# ======================================================


def _build_engine_nodes(pkg: StoryNodesPackage) -> Dict[str, Dict]:
    """
    把 StoryNode 轉成 engine 原本吃的 dict 結構
    """
    out: Dict[str, Dict] = {}

    for node_id, node in pkg.nodes.items():
        out[node_id] = _build_single_node(node_id, node)

    return out


def _build_single_node(node_id: str, node: StoryNode) -> Dict:
    data: Dict = {
        "title": node.title,
        "narration": _build_narration(node.narration),
        "choices": _build_choices(node.choices),
    }

    # optional fields
    if node.solution_index is not None:
        data["solution_index"] = node.solution_index

    if node.can_replay is not None:
        data["can_replay"] = node.can_replay

    if node.can_quit is not None:
        data["can_quit"] = node.can_quit

    return data


def _build_narration(items: list[NarrationItem]) -> str:
    """
    Engine 目前吃的是「一整段 narration 字串」
    """
    parts: list[str] = []
    for it in items:
        parts.append(f"{_role_label(it.role)}：{it.text}")
    return "\n\n".join(parts)


def _role_label(role: str) -> str:
    """
    Story role → engine 顯示名
    """
    mapping = {
        "narrator": "旁白",
        "feifei": "霏霏",
        "lele": "樂樂",
        "teacher": "老師",
        "student": "同學",
    }
    return mapping.get(role, role)


def _build_choices(items: list[ChoiceItem]) -> list[Dict]:
    out: list[Dict] = []
    for c in items:
        out.append(
            {
                "text": c.text,
                "next": c.next,
                "enabled": c.enabled,
                "tag": c.tag,
            }
        )
    return out


# ======================================================
# Solve rule（系統規則，不屬於故事）
# ======================================================


def _build_solve_rule() -> Dict:
    """
    固定使用 A 方案（solution_index）
    """
    return {
        "accuse_node": "final_accuse",
        "ending_clear_node": "scene_10_ending_clear",
        "ending_nudge_node": "scene_10_ending_nudge",
        "ending_defer_node": "scene_10_ending_defer",
        "end_screen_node": "quit",
        "use_solution_index": True,
    }
