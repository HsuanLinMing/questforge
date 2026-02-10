# src/questforge/ai/story_spec_v1.py
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

JsonDict = Dict[str, Any]

# 你想用來當「語氣/節奏錨點」的範例故事（只學節奏，不得照抄）
STYLE_EXAMPLE_FILE = Path("src/questforge/content/story_case_class_party_bag.py")

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


def _strip_code_fence(s: str) -> str:
    t = (s or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def extract_style_example(max_lines: int = 180) -> str:
    """
    讀取範例故事檔案前段，作為「節奏/語氣」錨點（few-shot）
    """
    if not STYLE_EXAMPLE_FILE.exists():
        return ""
    lines = STYLE_EXAMPLE_FILE.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[:max_lines]).strip()


@dataclass
class StorySpecV1:
    """
    規範驅動（Spec-driven）
    - 這裡集中：規範文字載入、prompt 組裝、品質 gate、文字清洗/去重
    - runtime generator 只跑流程，不再塞一堆寫死文案
    """

    # ----------------------------
    # Prompt sources
    # ----------------------------
    prompts_dir: Path = Path("src/questforge/ai/prompts")

    # ✅ runtime 給 AI 的規範檔（建議包含這些）
    # ⚠️ 不建議把 story_case_template_v1.md 丟進 runtime（會引導成 Python 檔案格式）
    core_files: List[str] = None  # set in __post_init__

    # ----------------------------
    # Theme constraints
    # ----------------------------
    allowed_background_themes: List[str] = None  # set in __post_init__
    banned_proper_nouns: List[str] = None  # set in __post_init__

    # ----------------------------
    # Tone / safety constraints
    # ----------------------------
    forbidden_opening_terms: List[str] = None  # set in __post_init__
    forbidden_opening_replacements: Dict[str, str] = None  # set in __post_init__
    gamey_patterns: List[str] = None  # set in __post_init__
    competition_drift_map: Dict[str, str] = None  # set in __post_init__

    # ----------------------------
    # Quality gate thresholds
    # ----------------------------
    opening_min_paragraphs: int = 22
    min_scene_nodes_after_required: int = 2

    # ✅ 你要「線索自然度」：不只看動詞次數，還要看「具體物件/場景/可觀察細節」
    min_clue_beats: int = 6
    min_concrete_clue_hits: int = 5
    min_distinct_clue_objects: int = 4

    # 去重門檻：允許少量重複，但不要爆炸
    max_dup_paragraphs: int = 2

    # ----------------------------
    # Quality lists (lazy)
    # ----------------------------
    clue_beat_verbs: List[str] = None
    red_herring_cues: List[str] = None

    # ✅ 線索自然度：具體物件/痕跡關鍵字、以及「模板線索句」黑名單
    clue_object_keywords: List[str] = None
    generic_clue_phrases: List[str] = None

    def __post_init__(self) -> None:
        if self.core_files is None:
            self.core_files = [
                "story_prompt_v1.md",
                "schema_story_nodes.md",
                "guard_rules.md",
                "story_response_whitelist.md",
                "world_old_rival_module.md",  # 可開關
            ]
        if self.allowed_background_themes is None:
            self.allowed_background_themes = [
                "運動會",
                "園遊會",
                "才藝發表日",
                "校內比賽",
                "社團成果展",
            ]
        if self.banned_proper_nouns is None:
            self.banned_proper_nouns = ["千羽會"]

        if self.forbidden_opening_terms is None:
            self.forbidden_opening_terms = [
                "不見",
                "找不到",
                "遺失",
                "被偷",
                "可疑",
                "推理",
                "調查",
                "線索",
                "破案",
                "兇手",
                "嫌疑人",
            ]
        if self.forbidden_opening_replacements is None:
            self.forbidden_opening_replacements = {
                "不見": "沒放在手邊",
                "找不到": "一時想不起放哪",
                "遺失": "一時忘了放哪",
                "被偷": "好像被拿去別的地方",
                "可疑": "有點怪怪的",
                "推理": "想一想",
                "調查": "看看",
                "線索": "小細節",
                "破案": "把事情弄清楚",
                "兇手": "做了那件事的人",
                "嫌疑人": "可能跟事情有關的人",
            }

        if self.gamey_patterns is None:
            self.gamey_patterns = [
                "你覺得該怎麼辦",
                "你會怎麼做",
                "請選擇",
                "玩家",
                "如果你在這裡",
                "你覺得呢",
                "怎麼辦",
            ]

        if self.competition_drift_map is None:
            self.competition_drift_map = {
                "才藝": "比賽項目",
                "表演": "比賽",
                "上台展示": "上場比賽",
                "精彩的表演": "精彩的比賽",
                "練習表演": "練習比賽項目",
                "上台": "上場",
            }

    # ============================================================
    # Prompt loading
    # ============================================================

    def _read(self, p: Path) -> str:
        return p.read_text(encoding="utf-8").strip()

    def build_instructions(self, *, include_old_rival: bool) -> str:
        """
        runtime 用：把核心規範檔拼成 instructions 丟給 AI
        """
        blocks: list[str] = []
        for name in self.core_files:
            if (not include_old_rival) and name == "world_old_rival_module.md":
                continue
            fp = self.prompts_dir / name
            if fp.exists():
                blocks.append(f"\n\n# FILE: {name}\n{self._read(fp)}")
        return "\n".join(blocks).strip()

    # ============================================================
    # Theme
    # ============================================================

    def pick_theme(self, seed: Optional[int], nonce: str) -> str:
        base = f"{seed if seed is not None else 'null'}:{nonce}"
        h = int(hashlib.sha1(base.encode("utf-8")).hexdigest(), 16)
        return self.allowed_background_themes[h % len(self.allowed_background_themes)]

    # ============================================================
    # Text utils
    # ============================================================

    def split_paragraphs(self, narration: str) -> list[str]:
        return [x.strip() for x in (narration or "").split("\n\n") if x.strip()]

    def join_paragraphs(self, parts: list[str]) -> str:
        return "\n\n".join([x for x in parts if (x or "").strip()])

    def remove_banned_proper_nouns(self, s: str) -> str:
        out = s or ""
        for w in self.banned_proper_nouns:
            out = out.replace(w, "校園活動")
        return out

    def replace_forbidden_opening_terms(self, s: str) -> str:
        out = s or ""
        for w in self.forbidden_opening_terms:
            if w in out:
                out = out.replace(w, self.forbidden_opening_replacements.get(w, ""))
        return out

    def soften_daily_tone(self, s: str) -> str:
        """
        只做「柔化」而不是寫死內容：
        - 避免太大人/太遊戲提示
        - 允許吐槽，但不讓它變成「教學/規則宣告」
        """
        out = s or ""
        out = out.replace("可疑", "有點怪怪的")
        for p in self.gamey_patterns:
            out = out.replace(p, "霏霏：我們先慢慢把剛剛看到的事情說清楚。")
        return out

    def apply_competition_anti_drift(self, text: str, theme: str) -> str:
        if theme != "校內比賽":
            return text
        out = text or ""
        for a, b in self.competition_drift_map.items():
            out = out.replace(a, b)
        return out

    def normalize_opening_theme(self, narration: str, theme: str) -> str:
        parts = self.split_paragraphs(narration)
        if not parts:
            return narration

        head = self.join_paragraphs(parts[:3])
        found = None
        for t in self.allowed_background_themes:
            if t in head:
                found = t
                break

        if found and found != theme:
            for i in range(min(3, len(parts))):
                parts[i] = parts[i].replace(found, theme)
            return self.join_paragraphs(parts)

        if found == theme:
            return narration

        insert = (
            f"旁白：今天是學校的「{theme}」，一早就很熱鬧，走廊上都是忙進忙出的腳步聲。"
        )
        parts.insert(1 if len(parts) >= 1 else 0, insert)
        return self.join_paragraphs(parts)

    # ============================================================
    # De-dupe
    # ============================================================

    def dedupe_paragraphs_global(self, text: str) -> str:
        paras = self.split_paragraphs(text)
        out: list[str] = []
        seen: set[str] = set()

        for p in paras:
            key = re.sub(r"\s+", "", p)
            if len(key) < 12:
                out.append(p)
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(p)

        return self.join_paragraphs(out)

    def dedupe_paragraphs_with_seen(self, text: str, seen: set[str]) -> str:
        """
        ✅ 跨節點全局去重：避免 enrich 把同一句「先冷靜/先確認」貼到每個 scene
        """
        paras = self.split_paragraphs(text)
        out: list[str] = []
        for p in paras:
            key = re.sub(r"\s+", "", p)
            if len(key) < 12:
                out.append(p)
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        return self.join_paragraphs(out)

    def post_clean_opening(self, narration: str) -> str:
        out = narration or ""
        out = self.dedupe_paragraphs_global(out)
        return out

    # ============================================================
    # Meta helpers
    # ============================================================

    def ensure_case_id(self, meta: Dict[str, Any], forced_case_id: str | None) -> None:
        if forced_case_id:
            meta["case_id"] = forced_case_id
            return
        if not str(meta.get("case_id") or "").strip():
            meta["case_id"] = f"ai_{uuid.uuid4().hex[:10]}"

    # ============================================================
    # Quality reports / gate
    # ============================================================

    def _init_quality_lists(self) -> None:
        if self.clue_beat_verbs is None:
            self.clue_beat_verbs = [
                "注意到",
                "發現",
                "看見",
                "聽到",
                "聞到",
                "摸到",
                "撿起",
                "指著",
                "湊近",
                "低頭看",
                "抬頭看",
                "比對",
                "問",
                "詢問",
                "確認",
                "回想",
                "整理",
                "對照",
                "翻開",
                "打開",
                "掀起",
                "摸了一下",
                "聞了一下",
            ]
        if self.red_herring_cues is None:
            self.red_herring_cues = [
                "原來只是",
                "其實只是",
                "只是剛好",
                "只是碰巧",
                "結果只是",
                "後來才知道",
                "才發現不是",
                "並不是",
            ]
        if self.clue_object_keywords is None:
            # ✅ 具體物件/痕跡：提高「線索自然度」的最關鍵訊號
            self.clue_object_keywords = [
                # 紙類/貼類/印記
                "貼紙",
                "背紙",
                "膠帶",
                "雙面膠",
                "標籤",
                "字條",
                "便條",
                "紙屑",
                "紙片",
                "印章",
                "印記",
                "墨水",
                # 票卡/道具/容器
                "票",
                "卡",
                "號碼牌",
                "抽籤筒",
                "籤",
                "袋子",
                "紙袋",
                "背包",
                "盒子",
                "收納盒",
                "透明袋",
                "拉鍊",
                "扣環",
                # 現場痕跡
                "腳印",
                "水漬",
                "油漬",
                "粉末",
                "碎屑",
                "刮痕",
                "掉落",
                "裂痕",
                "皺皺",
                # 聲音/味道/觸感
                "味道",
                "香味",
                "刺鼻",
                "黏黏",
                "滑滑",
                "冰冰",
                "濕濕",
            ]
        if self.generic_clue_phrases is None:
            # ✅ 模板句：出現太多就代表「線索不自然」
            self.generic_clue_phrases = [
                "我們找到線索了",
                "這一定是線索",
                "關鍵線索",
                "真相只有一個",
                "我好像知道了",
                "一定是他做的",
                "就是這個了",
                "這很明顯",
                "毫無疑問",
            ]

    def collect_narration_text(self, nodes: Dict[str, Any]) -> str:
        chunks: list[str] = []
        for _nid, node in (nodes or {}).items():
            if not isinstance(node, dict):
                continue
            nar = node.get("narration")
            if isinstance(nar, str):
                chunks.append(nar)
            elif isinstance(nar, list):
                for it in nar:
                    if isinstance(it, dict):
                        chunks.append(str(it.get("text") or ""))
                    else:
                        chunks.append(str(it or ""))
        return "\n".join(chunks)

    def opening_paragraphs(self, nodes: Dict[str, Any]) -> int:
        s1 = nodes.get("scene_01_start")
        s1_nar = str(s1.get("narration") or "") if isinstance(s1, dict) else ""
        return len(self.split_paragraphs(s1_nar))

    def clue_quality_report(self, nodes: Dict[str, Any]) -> Dict[str, Any]:
        """
        ✅ 線索自然度報告：
        - beats：感官/確認/比對等動詞密度
        - concrete_hits：具體物件/痕跡關鍵字命中數（越高越像「真的在現場」）
        - distinct_objects：不同物件詞的覆蓋數（避免一直只講同一個貼紙）
        - generic_hits：模板線索句命中（越高越不自然）
        """
        self._init_quality_lists()
        blob = self.collect_narration_text(nodes)

        beats = 0
        for v in self.clue_beat_verbs:
            beats += blob.count(v)
        beats = min(beats, 99)

        has_rh = any(k in blob for k in self.red_herring_cues)

        concrete_hits = 0
        distinct_objects: set[str] = set()
        for kw in self.clue_object_keywords:
            c = blob.count(kw)
            if c > 0:
                concrete_hits += c
                distinct_objects.add(kw)
        concrete_hits = min(concrete_hits, 199)

        generic_hits = 0
        for g in self.generic_clue_phrases:
            if g in blob:
                generic_hits += blob.count(g)

        excluded = {
            "scene_01_start",
            "final_accuse",
            "scene_10_ending_clear",
            "scene_10_ending_nudge",
            "scene_10_ending_defer",
            "quit",
        }
        scene_nodes = [nid for nid in nodes.keys() if nid not in excluded]

        return {
            "clue_beats": beats,
            "concrete_hits": concrete_hits,
            "distinct_objects": len(distinct_objects),
            "generic_hits": generic_hits,
            "has_red_herring_turn": has_rh,
            "scene_nodes_count": len(scene_nodes),
        }

    def style_quality_report(self, nodes: Dict[str, Any]) -> Dict[str, Any]:
        blob = self.collect_narration_text(nodes)
        paras = [x.strip() for x in blob.split("\n\n") if x.strip()]

        qmarks = blob.count("？") + blob.count("?")

        second_person_hits = 0
        for p in self.gamey_patterns:
            if p in blob:
                second_person_hits += blob.count(p)

        dup_paras = 0
        seen: set[str] = set()
        for p in paras:
            key = re.sub(r"\s+", "", p)
            if len(key) < 12:
                continue
            if key in seen:
                dup_paras += 1
            else:
                seen.add(key)

        return {
            "question_marks": qmarks,
            "second_person_hits": second_person_hits,
            "dup_paragraphs": dup_paras,
        }

    def needs_enrich(self, *, nodes: Dict[str, Any]) -> bool:
        open_ok = self.opening_paragraphs(nodes) >= self.opening_min_paragraphs
        clue = self.clue_quality_report(nodes)
        style = self.style_quality_report(nodes)

        if not open_ok:
            return True
        if (
            int(clue.get("scene_nodes_count") or 0)
            < self.min_scene_nodes_after_required
        ):
            return True

        # ✅ 線索自然度 gate：不能只靠「注意到/發現」這種動詞堆疊
        if int(clue.get("clue_beats") or 0) < self.min_clue_beats:
            return True
        if int(clue.get("concrete_hits") or 0) < self.min_concrete_clue_hits:
            return True
        if int(clue.get("distinct_objects") or 0) < self.min_distinct_clue_objects:
            return True

        # ✅ 模板線索句太多：代表不自然（寧願 enrich）
        if int(clue.get("generic_hits") or 0) >= 2:
            return True

        if int(style.get("second_person_hits") or 0) >= 1:
            return True
        if int(style.get("dup_paragraphs") or 0) > self.max_dup_paragraphs:
            return True

        return False

    # ============================================================
    # Prompt builders
    # ============================================================

    def json_skeleton(self) -> str:
        return """
請只輸出 JSON（不要 markdown、不要 code fence、不要解釋）。
最外層只能有 meta + nodes。

{
  "meta": {
    "schema_version": "v1",
    "title": "故事標題",
    "tags": ["ai"]
  },
  "nodes": {
    "scene_01_start": {
      "title": "...",
      "narration": "至少 22 段；用 \\n\\n 分段；每段 1~2 句；以 旁白：/霏霏：/樂樂：/老師： 開頭",
      "choices": [{"text":"繼續聽故事","next":"（必須存在節點）"}]
    },
    "final_accuse": {
      "title": "...",
      "narration": "...",
      "choices": [
        {"text":"嫌疑人1","next":"scene_10_ending_clear"},
        {"text":"嫌疑人2","next":"scene_10_ending_nudge"},
        {"text":"嫌疑人3","next":"scene_10_ending_defer"},
        {"text":"我還不確定，交給老師","next":"scene_10_ending_defer"}
      ],
      "solution_index": 0
    },
    "scene_10_ending_clear": {
      "title": "...",
      "narration": "...",
      "choices": [{"text":"故事結束","next":"quit"}]
    },
    "scene_10_ending_nudge": {
      "title": "...",
      "narration": "...",
      "choices": [{"text":"故事結束","next":"quit"}]
    },
    "scene_10_ending_defer": {
      "title": "...",
      "narration": "...",
      "choices": [{"text":"故事結束","next":"quit"}]
    },
    "quit": {
      "title": "...",
      "narration": "...",
      "choices": [],
      "can_replay": true,
      "can_quit": true
    }
  }
}
""".strip()

    def build_user_prompt(
        self,
        *,
        rules_text: str,
        seed: Optional[int],
        nonce: str,
        theme: str,
        include_old_rival: bool,
    ) -> str:
        """
        ✅ 吐槽口吻 + 線索自然度優先
        - 你仍可從 runtime 那邊傳入 rules_text（例如：build_instructions 的結果）
        """
        instructions = self.build_instructions(include_old_rival=include_old_rival)
        style = extract_style_example()
        seed_line = f"{int(seed)}" if seed is not None else "null"

        extra = f"""
# ✅ 額外生成要求（runtime）
1) 背景主題只能選一個，且必須是以下之一：
   {", ".join(self.allowed_background_themes)}
   本次請使用主題：{theme}

2) 吐槽口吻（優先）：
   - 霏霏/樂樂像「一起出門的兩個小偵探」：會互虧、被打斷、吐槽一半又憋回去
   - 但不要變成一直在講道理；要像故事書自然對話

3) 線索自然度（優先）：
   - 每一個「小細節」都必須是可觀察的：物件/痕跡/聲音/味道/觸感/位置
   - 不能只寫「我們找到線索了」這種模板句（禁止）
   - 看到細節後，要有一小段角色對話把它「說成白話」：
     例如「這個背紙掉在這裡→代表剛剛有人貼過東西→那貼在哪？」
   - 至少要出現 4 種不同的具體物件/痕跡（貼紙/背紙/膠帶/票/袋子/盒子/印記/水漬…）
   - 至少 2 個中段 scene 是「自然搜尋」：問人、回到現場對照、翻找道具箱、比對時間/順序（不要模板流程）

4) 禁止「遊戲提示口吻」：
   - 禁止句型：你覺得該怎麼辦 / 你會怎麼做 / 請選擇 / 玩家
   - 可以有角色之間的問句（？），但不要在問讀者做選擇

5) 開場必須真的長（scene_01_start 至少 {self.opening_min_paragraphs} 段）：
   - 用生活細節把氣氛鋪滿
   - 不要重複同一句話、不要複製貼上段落
""".strip()

        if theme == "校內比賽":
            extra += """
6) 若主題是「校內比賽」：
   - 不要漂成才藝發表/表演
   - 抽籤要說清楚抽什麼（出場順序/分組/項目）＋至少 3 個項目
""".rstrip()

        old_rival_line = (
            "7) 可選世界觀：可出現『理念型反派／神秘大盜』的影子（不一定登場，不要變主壞人）。"
            if include_old_rival
            else ""
        )

        return f"""
{rules_text}

{instructions}

{extra}
{old_rival_line}

# 輸出格式（必須遵守）
- 只輸出一個 JSON object
- 最外層只能有 meta + nodes
- narration 用 \\n\\n 分段，且每段用「角色：內容」開頭（旁白/霏霏/樂樂/老師）

{self.json_skeleton()}

# 節奏錨點 A（只學節奏，不得照抄）
{GOLDEN_OPENING_EXAMPLE}

# 節奏錨點 B（只學語氣/段落，不得照抄）
{style}

# runtime 參數（不要輸出）
seed={seed_line}
nonce={nonce}

最後提醒：只輸出 JSON object
""".strip()

    def build_repair_prompt(self, *, raw_text: str, error: str, theme: str) -> str:
        style = extract_style_example()
        return f"""
你上一版 JSON 沒有通過驗證。請你「在不重寫整個故事」的前提下做修補（最小修改）。

# 驗證錯誤
{error}

# 本次主題（必須維持單一主題，不要雙主題）
theme={theme}

# 修補規則
- 你必須輸出「完整 JSON object」（不要 markdown、不要 code fence、不要解釋）
- 以「最小修改」修好錯誤：除了必要欄位，其他文字與節點內容盡量不動
- 不可改動故事核心事實，只補齊缺漏/修正格式/修掉違規句
- 吐槽口吻要保留、線索要更像「現場觀察」而不是模板句

# 節奏錨點（只學節奏，不得照抄）
{GOLDEN_OPENING_EXAMPLE}

# 語氣錨點（只學語氣/段落，不得照抄）
{style}

# 你要修補的上一版 JSON
{raw_text}
""".strip()

    def build_enrich_prompt(
        self, *, raw_json: str, theme: str, rep: Dict[str, Any]
    ) -> str:
        style = extract_style_example()
        return f"""
你要把下面這份故事 JSON 做「最小修改」的補強，目標是：
- scene_01_start 至少 {self.opening_min_paragraphs} 段（\\n\\n 分段），段落要自然、像故事書
- 中段至少 2 個 scene 做自然搜尋（問人/回到現場/對照道具/被打斷/再確認）
- ✅ 線索自然長出來：每個小細節都必須是「具體可觀察」的物件/痕跡/聲音/味道/觸感/位置
- ✅ 禁止模板線索句（如：我們找到線索了 / 這一定是線索 / 關鍵線索）
- ✅ 吐槽口吻要保留：互虧、插曲、被打斷，但不要變教條

⚠️ 非常重要：
- 你可以有角色之間的問句（？），但不要問讀者要選什麼
- 不要複製貼上段落，避免重複
- 保留原本故事核心事實，不要推翻事件
- 至少出現 4 種不同的具體物件/痕跡（貼紙/背紙/膠帶/票/袋子/盒子/印記/水漬…）

# 目前品質檢查（不要輸出）
rep={json.dumps(rep, ensure_ascii=False)}

# 本次主題
theme={theme}

# 節奏錨點（只學節奏，不得照抄）
{GOLDEN_OPENING_EXAMPLE}

# 語氣錨點（只學語氣/段落，不得照抄）
{style}

# 只輸出完整 JSON object（不要 markdown、不要解釋）

# 你要修補的 JSON
{raw_json}
""".strip()
