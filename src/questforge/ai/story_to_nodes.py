# src/questforge/ai/story_to_nodes.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple
from questforge.ai.schemas import StoryPackage


def _n(*paras: str) -> str:
    # narration 統一用 \n\n 分段
    cleaned = []
    for p in paras:
        s = (p or "").strip()
        if not s:
            continue
        # 將單行換行整理成段落
        s = "\n".join([ln.strip() for ln in s.splitlines() if ln.strip()])
        cleaned.append(s)
    return "\n\n".join(cleaned).strip()


def story_package_to_case(story: StoryPackage) -> Tuple[Dict[str, Any], str, Dict[str, Any], str]:
    """
    回傳: (nodes, start_node, solve_rule, title)
    - solve_rule 用 use_solution_index: True（暫時讓「交給老師」當正解）
    """
    title = (story.title or "").strip() or "AI 生成案件"
    scenes = list(story.scenes or [])

    # suspects：取非主角/老師的角色名字，最多 3 個
    suspects: List[str] = []
    for ch in (story.characters or []):
        nm = (ch.name or "").strip()
        role = (ch.role or "").strip()
        if not nm:
            continue
        if role in ("霏霏", "樂樂", "老師"):
            continue
        if nm not in suspects:
            suspects.append(nm)
        if len(suspects) >= 3:
            break
    if not suspects:
        suspects = ["小杰", "小安", "小米"]  # 兜底

    nodes: Dict[str, Any] = {}

    # scene_01_start：prologue + 第一幕
    s0 = scenes[0] if scenes else None
    nodes["scene_01_start"] = {
        "title": (s0.title if s0 else "開場") or "開場",
        "narration": _n(story.prologue, (s0.narration if s0 else "")),
        "choices": [{"text": "繼續聽故事", "next": "scene_02"}],
    }

    # scene_02..scene_0N：依 story.scenes
    for i, sc in enumerate(scenes[1:], start=2):
        nid = f"scene_{i:02d}"
        next_id = f"scene_{i+1:02d}" if (i < len(scenes)) else "final_accuse"
        nodes[nid] = {
            "title": (sc.title or f"場景 {i}").strip(),
            "narration": _n(sc.narration),
            "choices": [{"text": "繼續聽故事", "next": next_id}],
        }

    # final_accuse：把 cooldown + teacher_scene 放在這裡
    accuse_choices = [{"text": nm, "next": "scene_10_ending_nudge"} for nm in suspects]
    accuse_choices.append({"text": "我還不確定，交給大人", "next": "scene_10_ending_defer"})

    nodes["final_accuse"] = {
        # ✅ 暫時讓「交給老師」當正解（等你之後接 evaluator/真正犯人再改）
        "solution_index": len(accuse_choices) - 1,
        "title": "指認時間",
        "narration": _n(
            "旁白：霏霏和樂樂先停一下，決定先把看到的事情說清楚。",
            story.cooldown_dialogue,
            story.teacher_scene,
        ),
        "choices": accuse_choices,
    }

    # endings：你可以用 open_ending 變三種版本（先簡化）
    nodes["scene_10_ending_clear"] = {
        "title": "完整的結局",
        "narration": _n(story.open_ending),
        "choices": [{"text": "故事結束", "next": "quit"}],
    }
    nodes["scene_10_ending_nudge"] = {
        "title": "差一點的結局",
        "narration": _n(story.open_ending),
        "choices": [{"text": "故事結束", "next": "quit"}],
    }
    nodes["scene_10_ending_defer"] = {
        "title": "交給老師的結局",
        "narration": _n(story.open_ending),
        "choices": [{"text": "故事結束", "next": "quit"}],
    }

    nodes["quit"] = {"choices": [], "can_replay": True}

    solve_rule = {
        "accuse_node": "final_accuse",
        "ending_check_node": "",
        "ending_clear_node": "scene_10_ending_clear",
        "ending_nudge_node": "scene_10_ending_nudge",
        "ending_defer_node": "scene_10_ending_defer",
        "end_screen_node": "quit",
        "reason_node": "",
        "reason_options": [],
        "reason_mode": "choice",
        "use_solution_index": True,
    }

    return nodes, "scene_01_start", solve_rule, title
