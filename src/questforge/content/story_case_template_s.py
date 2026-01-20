


## Stage 2 — 案件模板（Narration-only / 版本S）


from __future__ import annotations

"""QuestForge 案件模板（Narration-only / 版本 S 風格）。

用途：給你開新案、或把 beats 版本改成 narration 版本時，直接複製這份。

規則：
- 每個 node 只留：title / narration / choices
- narration 用 _n("角色：內容", ...) 組起來
- choices 的 next 一律指向既有 node id（或 quit）
"""

from typing import Dict, Any


def _n(*lines: str) -> str:
    """narration 統一：用『角色：內容』換行；空字串會被濾掉。"""
    return "\n\n".join([x for x in lines if (x or "").strip()])


# ------------------------------------------------------------
# 範例節點（請依案件調整）
# ------------------------------------------------------------
STORY_NODES: Dict[str, Dict[str, Any]] = {
    "scene_01_start": {
        "title": "開場",
        "narration": _n(
            "旁白：這裡是故事開場。",
            "霏霏：我們先看看發生什麼事。",
            "樂樂：我覺得怪怪的。",
        ),
        "choices": [
            {"text": "繼續", "next": "scene_02_incident"},
        ],
    },

    "scene_02_incident": {
        "title": "事件發生",
        "narration": _n(
            "旁白：事件突然發生，現場變得很混亂。",
            "霏霏：先不要急著猜。",
            "樂樂：我們先看清楚。",
        ),
        "choices": [
            {"text": "去看看", "next": "scene_03_investigate"},
        ],
    },

    "scene_03_investigate": {
        "title": "觀察與調查",
        "narration": _n(
            "旁白：你們靠近一點點，注意到一些小細節。",
            "霏霏：我覺得要把話講清楚，不能越講越大。",
        ),
        "choices": [
            {"text": "我想先說說看", "next": "final_accuse"},
            {"text": "再看一下", "next": "scene_03_investigate"},
        ],
    },

    # ✅ 指認節點（你也可以叫 accuse / final_accuse，solve_rule 會對應）
    "final_accuse": {
        "title": "你覺得最有可能跟誰有關？",
        "narration": _n(
            "旁白：大家都在等你說完。",
            "霏霏：（小聲）你想怎麼說都可以。",
        ),
        "choices": [
            {"text": "嫌疑人A", "next": "ending"},
            {"text": "嫌疑人B", "next": "ending"},
            {"text": "我還不確定，先去確認", "next": "ending"},
        ],
    },

    "ending": {
        "title": "尾聲",
        "narration": _n(
            "旁白：事情慢慢被講清楚。",
            "旁白：你沒有急著亂喊名字，所以沒有冤枉人。",
        ),
        "choices": [
            {"text": "故事結束", "next": "quit"},
        ],
    },

    # ✅ 統一 end screen 節點（建議所有案件都放）
    "quit": {
        "title": "故事結束",
        "narration": "旁白：你聽完了一個故事。",
        "choices": [],
        "can_replay": True,
        "can_quit": True,
    },
}
