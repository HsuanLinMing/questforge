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
from .story_case_sports_sticker import STORY_NODES as SPORTS_STICKER_NODES
from .story_case_class_party_bag import STORY_NODES as SPORTS_STICKER_NODES

CASES = {
    "2": {
        "title": "校園案：運動會貼紙日",
        "start": "start",
        "nodes": SPORTS_STICKER_NODES,
        "solve_rule": {
            # ----------------------------
            # 流程節點（原本保留）
            # ----------------------------
            "accuse_node": "accuse",
            "ending_check_node": "",
            "ending_wrong_node": "",

            # ----------------------------
            # ✅ 互動節奏（方案A：2次互動）
            # 第一次互動：中段輕推理（voice/text）
            # 第二次互動：accuse_node（指認）
            # ----------------------------
            "first_interaction_node": "mid_reason",   # 你在 STORY_NODES 裡新增一個中段互動節點
            "first_interaction_mode": "voice",        # voice/text；voice 最後一樣當 text 處理
            "reason_mode": "voice",                   # 保留舊欄位，避免你舊 code 讀不到

            # ----------------------------
            # ✅ 推理成熟度（不卡關）
            # ----------------------------
            "threshold": 3,

            # ----------------------------
            # ✅ 嫌疑人（engine 用 id；UI 可用 display）
            # ----------------------------
            "suspects": {
                "dongdong": {
                    "display": "飯糰啵啵（白白吊飾）",  # ✅ 新增：更好記
                    "support": {
                        "dongdong_hug_passport": 2,
                        "tape_was_pulled": 1,
                        "dongdong_restless": 1,         # 建議補上（你 expected_evidence 有用到）
                    }
                },
                "mei": {
                    "display": "膠帶小黏（手上常黏黏）",
                    "support": {
                        "mei_took_tape": 1,
                        "mei_near_table": 1,
                        "mei_tense_bag": 1,
                    }
                },
                "ali": {
                    "display": "鉛筆小刺（一直在找橡皮擦）",
                    "support": {
                        "ali_frustrated": 1,
                    }
                },
            },

            # ----------------------------
            # ✅ 第一次互動：輕推理選項（「怪怪的」觀察）
            # 注意：文字要像孩子、像在故事裡講，不像考題
            # ----------------------------
            "reason_options": [
                {
                    "id": "dongdong_hug_passport",
                    "text": "他一直把運動護照抱很緊，手都不放開",
                    "expected_evidence": ["dongdong_hug_passport", "dongdong_restless"],
                },
                {
                    "id": "mei_took_tape",
                    "text": "我看到她拿過膠帶，可是我不確定是不是在修東西",
                    "expected_evidence": ["mei_took_tape", "mei_near_table", "mei_tense_bag"],
                },
                {
                    "id": "tape_was_pulled",
                    "text": "地上有一條透明背紙，像被撕下來的",
                    "expected_evidence": ["tape_was_pulled"],
                },
                {
                    "id": "support_uncertain",
                    "text": "我還不確定，想先交給老師",
                    "expected_evidence": [],  # 這個就是安全出口
                },
            ],

            # 第一次互動回傳的 node（你也可以沿用舊的 reason_node）
            "reason_node": "mid_reason",

            # ----------------------------
            # ✅ 正解只用於結局揭曉／教育引導，不當卡關
            # ----------------------------
            "correct_suspect": "dongdong",

            # ----------------------------
            # ✅ 可選偵探回顧（不是考試，可關閉）
            # ----------------------------
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
                        "我看到她拿過膠帶（但也可能只是修東西）",
                        "地上有透明背紙，像被撕下來的",
                    ],
                    "after": "霏霏：你把『看到的小細節』說出來，推理就會更清楚喔。",
                }
            ],
        },
    },
}
