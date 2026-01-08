# 案件清單（像 Flutter 的路由/選單資料）
# Flutter 類比：List<CaseItem> 用來 build Menu

from .story_case_festival_medal import STORY_NODES as FESTIVAL_MEDAL_NODES
from .story_case_sports_sticker import STORY_NODES as SPORTS_STICKER_NODES
from .story_case_class_party_bag import STORY_NODES as CLASS_PARTY_BAG_NODES

CASES = {
    "1": {
        "title": "慶典案：甜甜點心節的金色獎牌",
        "start": "start",
        "nodes": FESTIVAL_MEDAL_NODES,
        "solve_rule": {
            "accuse_node": "accuse",
            "correct_next": "ending_result",
            "wrong_next": "ending_wrong",
            "correct_choice_index": 1,  # 依你 final_accuse 的 choices 實際順序
        },
    },
    "2": {
        "title": "校園案：運動會貼紙日",
        "start": "start",
        "nodes": SPORTS_STICKER_NODES,
        "solve_rule": {
            "accuse_node": "accuse",
            "correct_next": "ending_result",
            "wrong_next": "ending_wrong",
            # ✅ 推理門檻
            "threshold": 3,
            "suspects": {
                "dongdong": {
                    "support": {
                        "dongdong_hug_passport": 2,
                        "dongdong_wants_seen": 2,
                        "tape_backing_on_floor": 1,
                    }
                },
                "mei": {"support": {"mei_took_tape": 1}},
                "ali": {"support": {"ali_frustrated": 1}},
            },
            "correct_suspect": "dongdong",
            # ✅ 可選的「偵探回顧」（不是考試）
            "confirm_quiz": [
                {
                    "q": "你是靠哪個小細節想到的？（選一個就好）",
                    "options": [
                        "dongdong_hug_passport",
                        "mei_took_tape",
                        "tape_backing_on_floor",
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
    "3": {
        "title": "校園案：同樂會分享袋不見了（反排擠）",
        "start": "start",
        "nodes": CLASS_PARTY_BAG_NODES,
        "solve_rule": {
            "accuse_node": "accuse",
            "correct_next": "ending_result",
            "wrong_next": "ending_wrong",
            "correct_choice_index": 2,  # 依你 final_accuse 的 choices 實際順序
        },
    },
}
