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
from .story_case_class_party_bag import STORY_NODES as CLASS_PARTY_BAG_NODES

CASES = {
    "2": {
        "title": "校園案：運動會貼紙日",
        "start": "start",
        "nodes": SPORTS_STICKER_NODES,
        "solve_rule": {
            "accuse_node": "accuse",
            "ending_check_node": "ending_check",
            "ending_wrong_node": "ending_wrong",
            # ✅ 推理門檻
            "threshold": 3,
            "suspects": {
                "dongdong": {
                    "support": {
                        "dongdong_hug_passport": 2,
                        "dongdong_wants_seen": 2,
                        "tape_was_pulled": 1,
                    }
                },
                "mei": {"support": {"mei_took_tape": 1}},
                "ali": {"support": {"ali_frustrated": 1}},
            },
            "reason_options": [
                {
                    "id": "dongdong_hug_passport",
                    "text": "東東一直把運動護照抱很緊、坐不住",
                    "expected_evidence": ["dongdong_hug_passport", "dongdong_restless"],
                },
                {
                    "id": "mei_took_tape",
                    "text": "小芽說她拿過膠帶（但也可能只是修封面）",
                    "expected_evidence": ["mei_tense_bag", "mei_near_table"],
                },
                {
                    "id": "tape_was_pulled",
                    "text": "地上有透明背紙，像被拉過",
                    "expected_evidence": ["tape_was_pulled"],
                },
            ],
            "reason_node": "accuse_reason",
            "correct_suspect": "dongdong",
            # ✅ 可選的「偵探回顧」（不是考試）
            "confirm_quiz": [
                {
                    "q": "你是靠哪個小細節想到的？（選一個就好）",
                    "options": [
                        "dongdong_hug_passport",
                        "mei_took_tape",
                        "tape_was_pulled",
                    ],
                    "labels": [
                        "東東一直把運動護照抱很緊、坐不住",
                        "小芽說她拿過膠帶（但她也可能只是修封面）",
                        "地上有透明背紙，像被拉過",
                    ],
                    "after": "霏霏：把你看到的『小細節』說出來，推理就會更清楚喔。",
                }
            ],
        },
    },
}
