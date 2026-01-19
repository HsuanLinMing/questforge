# 案件清單（像 Flutter 的路由/選單資料）
# Flutter 類比：List<CaseItem> 用來 build Menu
"""
solve_rule（Day8+ 語意）：

- accuse_node / ending_check_node / ending_wrong_node：
  是流程節點名稱（CLI/Session 用來跳轉）。

- threshold：
  ✅ 推理成熟度門檻（用於回饋分級），不是卡關條件。
  score >= threshold => good
  score >= threshold/2 => ok
  否則 weak

- suspects.{suspect_id}.support：
  ✅ 證據權重表（clue_key -> 分數）
  用玩家收集到的 clues 做加權總分（推理成熟度），不是判定能不能指認。

- correct_suspect：
  ✅ 只用於「結局揭曉/教育引導」，不作為卡關對錯判定。

- confirm_quiz：
  ✅ 可選的偵探回顧（反思自己的推理），不是考試，可關閉。
"""
from .story_case_festival_medal import STORY_NODES as FESTIVAL_MEDAL_NODES
from .story_case_class_party_bag import STORY_NODES as SPORTS_STICKER_NODES

CASES = {
    "2": {
        "title": "校園案：運動會貼紙日",
        # ✅ 對齊 STORY_NODES
        "start": "scene_01_start",
        "nodes": SPORTS_STICKER_NODES,
        "solve_rule": {
            # 流程節點（必須存在於 STORY_NODES）
            "accuse_node": "accuse",
            "ending_check_node": "ending_check",
            "ending_wrong_node": "ending_wrong",
            "reason_node": "mid_reason_01",
            "end_screen_node": "quit",
            # 互動節奏（方案A：2次互動）
            "first_interaction_node": "mid_reason_01",
            "first_interaction_mode": "voice",
            "reason_mode": "voice",
            # 推理成熟度（不卡關）
            "threshold": 3,
            # suspects（display 要跟 accuse choices 顯示一致）
            "suspects": {
                "dongdong": {
                    "display": "飯糰啵啵（白色吊飾）",
                    "support": {
                        "dongdong_hug_passport": 2,
                        "tape_was_pulled": 1,
                        "dongdong_restless": 1,
                    },
                },
                "mei": {
                    "display": "甜甜圈阿咚（餅乾放旁邊）",
                    "support": {
                        "mei_took_tape": 1,
                        "mei_near_table": 1,
                        "mei_tense_bag": 1,
                    },
                },
                "ali": {
                    "display": "鉛筆小刺（一直在找橡皮擦）",
                    "support": {
                        "ali_frustrated": 1,
                    },
                },
            },
            # 第一次互動：理由選項
            "reason_options": [
                {
                    "id": "dongdong_hug_passport",
                    "text": "他一直把運動護照抱很緊，手都不放開",
                    "expected_evidence": ["dongdong_hug_passport", "dongdong_restless"],
                },
                {
                    "id": "mei_took_tape",
                    "text": "我看到他把餅乾放在旁邊（但我不確定是不是重點）",
                    "expected_evidence": [
                        "mei_took_tape",
                        "mei_near_table",
                        "mei_tense_bag",
                    ],
                },
                {
                    "id": "tape_was_pulled",
                    "text": "地上有一條透明背紙，像被撕下來的",
                    "expected_evidence": ["tape_was_pulled"],
                },
                {
                    "id": "support_uncertain",
                    "text": "我還不確定，想先交給老師",
                    "expected_evidence": [],
                },
            ],
            "correct_suspect": "dongdong",
            "confirm_quiz": [
                {
                    "q": "你剛剛最在意哪個小細節？（選一個就好）",
                    "options": [
                        "dongdong_hug_passport",
                        "mei_took_tape",
                        "tape_was_pulled",
                    ],
                    "labels": [
                        "他一直把運動護照抱很緊，手都不放開",
                        "我看到他把餅乾放在旁邊（但也可能只是習慣）",
                        "地上有透明背紙，像被撕下來的",
                    ],
                    "after": "霏霏：你把『看到的小細節』說出來，推理就會更清楚喔。",
                }
            ],
        },
    },
}
