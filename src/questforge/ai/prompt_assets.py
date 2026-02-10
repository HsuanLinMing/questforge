# src/questforge/ai/prompt_assets.py
from __future__ import annotations

from pathlib import Path
from typing import List

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
CONTENT_DIR = Path(__file__).resolve().parents[1] / "content"

STYLE_EXAMPLE_FILE = CONTENT_DIR / "story_case_class_party_bag.py"

# -------------------------
# CLI（舊）: 產 python STORY_NODES = {...}
# -------------------------
CORE_FILES_CLI = [
    "story_prompt_v1.md",          # 世界觀母版
    "story_case_template_v1.md",   # python 檔模板
    "schema_story_nodes.md",       # ⚠️ 這份是「STORY_NODES = {...}」舊規格
    "guard_rules.md",
    "story_response_whitelist.md",
    "world_old_rival_module.md",   # 可開關
]

# -------------------------
# Runtime（新）: 產 StoryNodesPackage v1 JSON
# - 這裡刻意不 include schema_story_nodes.md / story_case_template_v1.md
#   避免模型被帶去輸出 STORY_NODES=... 或 python 檔
# -------------------------
CORE_FILES_RUNTIME = [
    "story_prompt_v1.md",
    "guard_rules.md",
    "story_response_whitelist.md",
    "world_old_rival_module.md",  # 可開關
]

# -------------------------
# Few-shot: 黃金開場（節奏錨點）
# -------------------------
GOLDEN_OPENING_EXAMPLE = """
【黃金開場示範（僅示範節奏，禁止照抄內容）】
旁白：今天的教室聞起來有點像紙箱味，因為大家把道具、海報、彩帶都搬進來了。

旁白：黑板上用粉筆寫著大大的四個字——「才・藝・日」。

霏霏：欸，老師寫字有把「才」寫得像菜耶。

樂樂：那今天是「菜藝日」嗎？我要表演——切菜！

霏霏：你先把刀放下，菜藝日也不給你刀。

旁白：老師在講台上拍了拍手，像拍蚊子一樣「啪！啪！」兩聲。

老師：各位小小表演家～道具袋先放到後面那張桌子，等下照順序上台喔。

樂樂：上台前我可以先練習尖叫嗎？

霏霏：你那個不是尖叫，是救護車。

旁白：後面那張桌子上貼了便利貼，寫著「道具袋停車場」。

樂樂：停車場？那我的道具袋要不要倒車入庫？

霏霏：你可以先把它停好，不要把別人的袋子撞歪。

旁白：這時候，有兩個同學一路小跑進來。

甜甜圈阿咚：我把我的呼拉圈帶來了！欸欸不要踩到！它很會滾！

鉛筆小刺：我的是魔術盒！可是我剛剛差點把自己變不見。

樂樂：哇你成功了嗎？

鉛筆小刺：沒有，我只是把盒子蓋子弄掉了。

霏霏：（笑）這叫「蓋子逃跑術」。

旁白：走廊外還傳來操場的廣播聲，像在催大家快一點。

廣播（值日生）：請表演的班級準備——不要邊走邊吃飯糰！

樂樂：誰邊走邊吃飯糰啦？

霏霏：你昨天就是。

樂樂：那是飯糰自己跑進我嘴巴的。

旁白：老師把名單拿在手上，一邊點名一邊看大家的袋子有沒有貼好名字。

老師：記得貼名字喔～貼名字是保護道具袋的魔法。

樂樂：（小聲）如果我貼兩張，是不是變成雙倍魔法？

霏霏：會變成雙倍黏，然後你自己撕不下來。

旁白：大家笑成一片，教室熱熱鬧鬧的，好像連椅子都在抖。

旁白：霏霏把樂樂的道具袋放好，還用手指戳了一下，確認它真的乖乖坐著。

霏霏：好，停車成功。不要再倒車了喔。

樂樂：收到！表演家出發！
""".strip()


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8").strip()


def _build_instructions(files: List[str], *, include_old_rival: bool) -> str:
    blocks: list[str] = []
    for name in files:
        if not include_old_rival and name == "world_old_rival_module.md":
            continue
        fp = PROMPTS_DIR / name
        if fp.exists():
            blocks.append(f"\n\n# FILE: {name}\n{_read(fp)}")
    return "\n".join(blocks).strip()


def build_instructions(*, include_old_rival: bool) -> str:
    """
    ✅ 保持相容：預設回 CLI 那套（舊 story_writer_cli 仍可用）
    """
    return _build_instructions(CORE_FILES_CLI, include_old_rival=include_old_rival)


def build_instructions_runtime(*, include_old_rival: bool) -> str:
    """
    ✅ Runtime 專用：避免引導模型輸出 python / STORY_NODES=
    """
    return _build_instructions(CORE_FILES_RUNTIME, include_old_rival=include_old_rival)


def extract_style_example() -> str:
    """抽取 story_case_class_party_bag.py 的前段作為節奏示範（第二個錨點）"""
    if not STYLE_EXAMPLE_FILE.exists():
        return ""
    lines = STYLE_EXAMPLE_FILE.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[:180]).strip()
