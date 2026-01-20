# src/questforge/content/cases.py
from __future__ import annotations

from .story_case_class_party_bag import STORY_NODES as SPORTS_STICKER_NODES


CASES = {

    # ✅ 新增：版本 S（千羽會）
    "3": {
        "title": "活動案：千羽會尾羽風波（版本S）",
        "start": "scene_01_start",
        "nodes": SPORTS_STICKER_NODES,
        "solve_rule": {
            # 指認節點
            "accuse_node": "final_accuse",

            # ✅ 版本S不走 ending_check（留空即可）
            "ending_check_node": "",

            # ✅ 三段結尾（由 GameSession 在 accuse 後分流）
            "ending_clear_node": "scene_10_ending_clear",
            "ending_nudge_node": "scene_10_ending_nudge",
            "ending_defer_node": "scene_10_ending_defer",

            # end screen（GameSession 用這個判定 show_end_screen）
            "end_screen_node": "quit",

            # ✅ 不做 reason gate / 不跳 ask_reason
            "reason_node": "",
            "reason_options": [],
            "reason_mode": "choice",

            # ✅ 分流門檻（你先用 3，因為你原本就填 3）
            "threshold": 3,

            # ✅ 正解（用來在「沒有 reason input / 沒有 support map」時，仍可做分流）
            "correct_suspect": "henry",

            # ✅ 指認選項 index → suspect id（final_accuse choices 順序若改了，這裡要同步）
            "accuse_choice_to_suspect": {
                "1": "henry",
                "2": "miaomiao",
                "3": "alei",
                # 4: 不確定 → 不填，會走 defer bucket
            },

            # suspects/support：版本S你不想逼小孩選理由，所以 support 空也沒關係
            "suspects": {
                "henry": {"display": "亨利爵士", "support": {}},
                "miaomiao": {"display": "喵喵（粉絲）", "support": {}},
                "alei": {"display": "阿雷（接待員）", "support": {}},
            },

            # ✅ nudge 範圍：差 1 分算差一點點（你可改 1 或 0）
            "ending_nudge_margin": 1,
        },
    },
}

# ✅ Day29：啟動時自動驗證
from questforge.content.validator import validate_cases_if_enabled
validate_cases_if_enabled(CASES)
