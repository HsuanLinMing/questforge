# src/questforge/content/cases.py
from __future__ import annotations

# [AUTO-IMPORTS]
from .story_case_generated_demo_v10 import STORY_NODES as CASE_4_NODES  # <- 讓 CLI 自動插入 import 在這行下面

from .story_case_class_party_bag import STORY_NODES as CLASS_PARTY_BAG_NODES

CASES = {
    # [AUTO-CASES]

    "4": {
        "title": "校園案：班上才藝日，大家的『表演道具袋』不見了",
        "start": "scene_01_start",
        "nodes": CASE_4_NODES,
        "solve_rule": {
            "accuse_node": "final_accuse",
            "ending_check_node": "",
            "ending_clear_node": "scene_10_ending_clear",
            "ending_nudge_node": "scene_10_ending_nudge",
            "ending_defer_node": "scene_10_ending_defer",
            "end_screen_node": "quit",

            "reason_node": "",
            "reason_options": [],
            "reason_mode": "choice",

            # ✅ A 方案：用 story 內的 final_accuse.solution_index 來判斷正解
            "use_solution_index": True,
        },
    },  # <- 讓 CLI 自動插入新 case 在這行下面

    "3": {
        "title": "活動案：千羽會尾羽風波（版本S）",
        "start": "scene_01_start",
        "nodes": CLASS_PARTY_BAG_NODES,
        "solve_rule": {
            "accuse_node": "final_accuse",
            "ending_check_node": "",
            "ending_clear_node": "scene_10_ending_clear",
            "ending_nudge_node": "scene_10_ending_nudge",
            "ending_defer_node": "scene_10_ending_defer",
            "end_screen_node": "quit",
            "reason_node": "",
            "reason_options": [],
            "reason_mode": "choice",
            "threshold": 3,
            "correct_suspect": "henry",
            "accuse_choice_to_suspect": {"1": "henry", "2": "miaomiao", "3": "alei"},
            "suspects": {
                "henry": {"display": "亨利爵士", "support": {}},
                "miaomiao": {"display": "喵喵（粉絲）", "support": {}},
                "alei": {"display": "阿雷（接待員）", "support": {}},
            },
            "ending_nudge_margin": 1,
        },
    },
}

from questforge.content.validator import validate_cases_if_enabled
validate_cases_if_enabled(CASES)
