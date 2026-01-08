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
            "accuse_node": "final_accuse",
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
            "accuse_node": "final_accuse",
            "correct_next": "ending_result",
            "wrong_next": "ending_wrong",
            "correct_choice_index": 1,
        },
    },
    "3": {
        "title": "校園案：同樂會分享袋不見了（反排擠）",
        "start": "start",
        "nodes": CLASS_PARTY_BAG_NODES,
        "solve_rule": {
            "accuse_node": "final_accuse",
            "correct_next": "ending_result",
            "wrong_next": "ending_wrong",
            "correct_choice_index": 2,  # 依你 final_accuse 的 choices 實際順序
        },
    },
}
