# src/questforge/ai/story_spec_v1.py
from __future__ import annotations

import hashlib
import json
import re
import textwrap
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

JsonDict = Dict[str, Any]

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


def extract_style_example(max_lines: int = 180) -> str:
    """抽取範例故事前段作為節奏示範（只學節奏/口吻，不可照抄內容）"""
    if not STYLE_EXAMPLE_FILE.exists():
        return ""
    lines = STYLE_EXAMPLE_FILE.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[:max_lines]).strip()


@dataclass
class StorySpecV1:
    """
    ✅ 原則：以「規範引導 AI 自行生成」為主。
    - spec 只負責：規範、gate、報告、repair/enrich 的指令。
    - 不在 spec 裡「寫死劇情」或做大量替換改寫。

    ✅ 本版關鍵修正：
    - 「事件」判定不靠關鍵字；必須存在 scene_02_incident 節點，並用它做 40% 延後 gate。
    - 不允許「幫小朋友整理線索/重點回顧/替讀者排除」的教學式總結（孩子要自己判斷與記住）。
      允許偶爾出現很離譜的假線索被吐槽，但不應每次都強制排除/整理。
    """

    prompts_dir: Path = Path("src/questforge/ai/prompts")
    core_files: List[str] = None  # set in __post_init__

    unsure_choice_text: str = "我還不確定，交給大人"

    # 開場段落數（以 \n\n 分段）
    opening_min_paragraphs: int = 22

    # 事件節點 id（用來判定「有事件」、用來算 40% gate）
    incident_node_id: str = "scene_02_incident"

    # 事件延後：必須在中後段第一次出現（用 incident_node_id 的位置計算）
    incident_min_ratio: float = 0.40
    incident_min_paragraphs_before: int = 16

    # 結尾完整性
    ending_min_paragraphs: int = 6

    # 事件後至少要有幾個自然搜尋 scene（避免事件一出就指認）
    min_scene_nodes_after_required: int = 2

    # 開場禁詞（scene_01_start 全禁：包含引號/轉述/台詞）
    incident_terms_for_opening_ban: List[str] = None
    forbidden_opening_terms: List[str] = None

    # 禁止 placeholder 命名
    banned_placeholders: List[str] = None

    # 禁止泛稱（要求配角要有名字）
    banned_generics: List[str] = None

    # 禁止遊戲提示口吻（不要對讀者下指令）
    gamey_patterns: List[str] = None

    # ✅ 禁止「替讀者整理/記重點/總結線索」口吻（全篇禁止）
    # （注意：不是禁止角色聊天說「我整理一下」，而是禁止出現「幫你整理重點/你要記住...」這種教學指令式總結）
    banned_reader_hint_patterns: List[str] = None

    # ✅ 開場「安全句型示範」（repair 用）
    opening_safe_patterns: List[str] = None

    # cases 殘影（避免帶到別案名詞）
    banned_proper_nouns: List[str] = None

    allowed_background_themes: Optional[List[str]] = None

    def __post_init__(self) -> None:
        if self.core_files is None:
            self.core_files = [
                "story_prompt_v1.md",
                "schema_story_nodes.md",
                "guard_rules.md",
                "story_response_whitelist.md",
                "world_old_rival_module.md",
            ]

        if self.allowed_background_themes is None:
            self.allowed_background_themes = [
                "校園活動",
                "公園",
                "夜市",
                "便利商店",
                "超市",
                "圖書館",
                "博物館",
                "車站",
                "公車上",
                "社區活動",
                "海邊",
                "露營區",
                "運動中心",
                "游泳池",
                "餐廳",
                "遊樂園",
                "寵物店",
                "文具店",
            ]

        if self.banned_proper_nouns is None:
            self.banned_proper_nouns = [
                "千羽會",
                "亨利爵士",
                "孔雀",
                "喵喵（粉絲）",
                "老鷹大翔",
            ]

        # ✅ 開場必禁：避免太早進案件的「事件/失竊/走失」字眼
        if self.incident_terms_for_opening_ban is None:
            self.incident_terms_for_opening_ban = [
                "不見",
                "找不到",
                "遺失",
                "被偷",
                "消失",
                "失蹤",
                "走失",
                "走散",
            ]

        if self.forbidden_opening_terms is None:
            self.forbidden_opening_terms = [
                "可疑",
                "奇怪",
                "不尋常",
                "出事",
                "開始調查",
                "推理",
                "真相",
                "嫌疑",
                "犯人",
            ]

        if self.banned_placeholders is None:
            self.banned_placeholders = [
                "學長A",
                "學長B",
                "學長C",
                "嫌疑人A",
                "嫌疑人B",
                "嫌疑人C",
                "嫌疑人甲",
                "嫌疑人乙",
                "嫌疑人丙",
            ]

        if self.banned_generics is None:
            self.banned_generics = [
                "紅色衣服",
                "那個男孩",
                "某位同學",
                "穿外套的人",
                "小朋友",
                "那個人",
            ]

        # ✅ 重要：這個詞太常用、且不一定代表「沒名字的配角」
        #（例如：店員喊「小朋友們小心」是自然台詞；留著會讓成功率大幅下降）
        self.banned_generics = [x for x in (self.banned_generics or []) if x != "小朋友"]

        if self.gamey_patterns is None:
            self.gamey_patterns = [
                "你覺得該怎麼辦",
                "你會怎麼做",
                "請選擇",
                "玩家",
                "如果你在這裡",
            ]

        if self.banned_reader_hint_patterns is None:
            # ✅ 全篇禁：不要幫讀者「整理/記住/排除」的教學式總結
            self.banned_reader_hint_patterns = [
                "幫你整理",
                "我幫你整理",
                "我們幫你整理",
                "重點是",
                "重點整理",
                "整理重點",
                "請記住",
                "你要記住",
                "記得這些",
                "把這些記起來",
                "線索總結",
                "線索整理",
                "現在我們把線索整理",
                "因此可以排除",
                "所以可以排除",
                "我們排除",
                "這就排除",
                "答案就是",
                "正確答案是",
                "總結一下",
                "整理一下線索",
                "所以答案是",
                "結論是",
                "換句話說",
            ]

        if self.opening_safe_patterns is None:
            # ✅ 重要：不得包含 incident_terms_for_opening_ban / forbidden_opening_terms
            self.opening_safe_patterns = [
                "旁白：有人把眉毛皺成小山丘，手指在桌面上敲了兩下。",
                "霏霏：等等～我想再看一次，我剛剛是不是放到別邊了？",
                "樂樂：我剛才腦袋像被橡皮擦擦過一小塊，空白一下下！",
                "老師：先把桌面整理一下～不要把東西疊成小山喔。",
                "旁白：椅子發出「吱呀」一聲，好像也在偷笑。",
                "配角：我這裡有貼紙！要不要先貼名字，像貼護身符！",
                "霏霏：你不要一直轉圈啦，地板都要暈了。",
                "樂樂：我沒有轉圈，我是在練習『安靜的旋轉』！",
                "旁白：大家忙著準備，像一群小蜜蜂嗡嗡飛。",
                "老師：先別急著亂跑～跟著排隊，一個一個來。",
            ]

    # ============================================================
    # Prompt loading
    # ============================================================

    def _read(self, p: Path) -> str:
        return p.read_text(encoding="utf-8").strip()

    def build_instructions(self, *, include_old_rival: bool) -> str:
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
        if not self.allowed_background_themes:
            return ""
        base = f"{seed if seed is not None else 'null'}:{nonce}"
        h = int(hashlib.sha1(base.encode("utf-8")).hexdigest(), 16)
        return self.allowed_background_themes[h % len(self.allowed_background_themes)]

    # ============================================================
    # Text helpers
    # ============================================================

    def split_paragraphs(self, narration: str) -> list[str]:
        return [x.strip() for x in (narration or "").split("\n\n") if x.strip()]

    def collect_narration_text(self, nodes: Dict[str, Any]) -> str:
        chunks: list[str] = []
        for _nid, node in (nodes or {}).items():
            if not isinstance(node, dict):
                continue
            nar = node.get("narration")
            if isinstance(nar, str):
                chunks.append(nar)
        return "\n".join(chunks)

    def opening_paragraphs(self, nodes: Dict[str, Any]) -> int:
        s1 = nodes.get("scene_01_start")
        s1_nar = str(s1.get("narration") or "") if isinstance(s1, dict) else ""
        return len(self.split_paragraphs(s1_nar))

    def _opening_banned_all(self) -> List[str]:
        # scene_01_start 全禁：事件字眼 + 推理/異常口吻字眼
        return list(
            dict.fromkeys(
                (self.incident_terms_for_opening_ban or [])
                + (self.forbidden_opening_terms or [])
            )
        )

    def _has_any_opening_banned(self, text: str) -> List[str]:
        hits: List[str] = []
        for w in self._opening_banned_all():
            if w and (w in (text or "")):
                hits.append(w)
        return hits

    def _has_any_reader_hint_banned(self, text: str) -> List[str]:
        hits: List[str] = []
        t = text or ""
        for w in self.banned_reader_hint_patterns or []:
            if w and (w in t):
                hits.append(w)
        return hits

    # ============================================================
    # Quality report / gate（只產生報告，不改寫內容）
    # ============================================================

    def clue_quality_report(self, nodes: Dict[str, Any]) -> Dict[str, Any]:
        blob = self.collect_narration_text(nodes)
        paras = [x.strip() for x in (blob or "").split("\n\n") if x.strip()]

        obs_verbs = [
            "看到",
            "看見",
            "發現",
            "注意到",
            "摸到",
            "撿到",
            "聞到",
            "聽到",
            "踩到",
            "翻開",
            "指著",
        ]
        loc_marks = [
            "地上",
            "桌下",
            "桌上",
            "椅子下",
            "角落",
            "旁邊",
            "附近",
            "後面",
            "門口",
        ]

        def _clean_span(s: str) -> str:
            s = (s or "").strip()
            s = re.sub(r"^[：:\s]+", "", s)
            s = re.sub(r"[，,。！？!?\n\r\t].*$", "", s)
            s = s.strip()
            if len(s) > 10:
                s = s[:10]
            return s

        noun_set: set[str] = set()
        hits = 0

        verb_pat = r"(" + "|".join(map(re.escape, obs_verbs)) + r")([^。！？\n]{1,16})"
        loc_pat = r"(" + "|".join(map(re.escape, loc_marks)) + r")([^。！？\n]{1,16})"

        for p in paras:
            for m in re.finditer(verb_pat, p):
                span = _clean_span(m.group(2))
                if span:
                    noun_set.add(span)
                    hits += 1
            for m in re.finditer(loc_pat, p):
                span = _clean_span(m.group(2))
                if span:
                    noun_set.add(span)
                    hits += 1

        # ✅ 事件後自然探索 scene：只算 incident 後面的 nodes（排除 final/ending/quit）
        excluded = {
            "scene_01_start",
            "scene_01_warmup_2",
            "scene_01_warmup_3",
            "final_accuse",
            "scene_10_ending_clear",
            "scene_10_ending_nudge",
            "scene_10_ending_defer",
            "quit",
        }

        ordered = list((nodes or {}).keys())
        inc_idx = ordered.index(self.incident_node_id) if self.incident_node_id in ordered else -1

        post_scene_nodes: list[str] = []
        if inc_idx >= 0:
            for nid in ordered[inc_idx + 1 :]:
                if nid in excluded:
                    continue
                post_scene_nodes.append(nid)

        return {
            "object_hits": min(hits, 199),
            "distinct_objects": len(noun_set),
            "scene_nodes_count": len(post_scene_nodes),  # ✅ now truly "after incident"
        }

    def style_quality_report(self, nodes: Dict[str, Any]) -> Dict[str, Any]:
        blob = self.collect_narration_text(nodes)

        second_person_hits = 0
        for p in self.gamey_patterns or []:
            if p in blob:
                second_person_hits += blob.count(p)

        # ✅ 教學式「幫你整理/記住重點」命中
        reader_hint_hits = 0
        for p in self.banned_reader_hint_patterns or []:
            if p in blob:
                reader_hint_hits += blob.count(p)

        paras = [x.strip() for x in blob.split("\n\n") if x.strip()]
        seen: set[str] = set()
        dup = 0
        for p in paras:
            key = re.sub(r"\s", "", p)
            if len(key) < 12:
                continue
            if key in seen:
                dup += 1
            else:
                seen.add(key)

        return {
            "second_person_hits": second_person_hits,
            "reader_hint_hits": reader_hint_hits,
            "dup_paragraphs": dup,
        }

    def needs_enrich(self, *, nodes: Dict[str, Any]) -> bool:
        if self.opening_paragraphs(nodes) < self.opening_min_paragraphs:
            return True

        clue = self.clue_quality_report(nodes)
        style = self.style_quality_report(nodes)

        if int(clue.get("scene_nodes_count") or 0) < self.min_scene_nodes_after_required:
            return True
        if int(clue.get("distinct_objects") or 0) < 4:
            return True
        if int(style.get("second_person_hits") or 0) >= 1:
            return True
        if int(style.get("reader_hint_hits") or 0) >= 1:
            return True
        if int(style.get("dup_paragraphs") or 0) > 2:
            return True

        rep = self.enrich_report(nodes=nodes, theme="(n/a)")
        if rep.get("reasons"):
            return True

        return False

    # ============================================================
    # Enrich gate (report only)
    # ============================================================

    def _has_kana(self, s: str) -> bool:
        return re.search(r"[\u3040-\u30ff]", s or "") is not None

    def _scene01_text(self, nodes: Dict[str, Any]) -> str:
        s1 = nodes.get("scene_01_start")
        if isinstance(s1, dict):
            return str(s1.get("narration") or "")
        return ""

    def _all_text(self, nodes: Dict[str, Any]) -> str:
        return self.collect_narration_text(nodes)

    def _final_accuse_choices(self, nodes: Dict[str, Any]) -> List[str]:
        fa = nodes.get("final_accuse")
        if not isinstance(fa, dict):
            return []
        ch = fa.get("choices")
        if not isinstance(ch, list):
            return []
        out: List[str] = []
        for it in ch:
            if isinstance(it, dict):
                out.append(str(it.get("text") or "").strip())
        return out

    def _pre_accuse_text_blob(self, nodes: Dict[str, Any]) -> str:
        excluded = {
            "final_accuse",
            "scene_10_ending_clear",
            "scene_10_ending_nudge",
            "scene_10_ending_defer",
            "quit",
        }
        parts: List[str] = []
        for nid, node in (nodes or {}).items():
            if nid in excluded:
                continue
            if isinstance(node, dict):
                nar = node.get("narration")
                if isinstance(nar, str) and nar.strip():
                    parts.append(nar)
        return "\n".join(parts)

    def _node_narration(self, nodes: Dict[str, Any], nid: str) -> str:
        node = (nodes or {}).get(nid)
        if isinstance(node, dict):
            nar = node.get("narration")
            if isinstance(nar, str):
                return nar
        return ""

    def _ordered_node_ids(self, nodes: Dict[str, Any]) -> List[str]:
        return list((nodes or {}).keys())

    def _find_first_incident_node(self, nodes: Dict[str, Any]) -> Optional[str]:
        # ✅ 事件判定完全靠結構
        if self.incident_node_id in (nodes or {}):
            return self.incident_node_id
        return None

    def _count_total_paragraphs(self, nodes: Dict[str, Any]) -> int:
        total = 0
        for nid in self._ordered_node_ids(nodes):
            nar = self._node_narration(nodes, nid)
            if nar:
                total += len(self.split_paragraphs(nar))
        return total

    def _count_paragraphs_before_node(self, nodes: Dict[str, Any], until_nid: str) -> int:
        total = 0
        for nid in self._ordered_node_ids(nodes):
            if nid == until_nid:
                break
            nar = self._node_narration(nodes, nid)
            if nar:
                total += len(self.split_paragraphs(nar))
        return total

    def _ending_ok(self, text: str) -> bool:
        t = text or ""
        has_reason = any(k in t for k in ["因為", "所以", "原來", "其實是", "其實"])
        has_apology = any(k in t for k in ["對不起", "道歉", "抱歉"])
        has_teach = any(k in t for k in ["下次", "以後", "記得", "學到", "提醒"])
        paras = len(self.split_paragraphs(t))
        return has_reason and has_apology and has_teach and paras >= self.ending_min_paragraphs

    def enrich_fail_reasons(self, *, nodes: Dict[str, Any], theme: str) -> List[str]:
        reasons: List[str] = []

        s01 = self._scene01_text(nodes)
        if not s01.strip():
            reasons.append("scene_01_start narration 為空")
            return reasons

        open_paras = len(self.split_paragraphs(s01))
        if open_paras < self.opening_min_paragraphs:
            reasons.append(f"scene_01_start 段落不足（{open_paras} < {self.opening_min_paragraphs}）")

        # ✅ scene_01_start 禁詞
        open_hits = self._has_any_opening_banned(s01)
        if open_hits:
            reasons.append(f"scene_01_start 出現開場禁詞（包含轉述/台詞/引號）：{open_hits}")

        if self._has_kana(s01):
            reasons.append("scene_01_start 出現日文假名（平假名/片假名）")

        gen_hits = [w for w in (self.banned_generics or []) if w in s01]
        if gen_hits:
            reasons.append(f"scene_01_start 出現泛稱（請改成有名字的配角）：{gen_hits}")

        blob_all = self._all_text(nodes)

        ph_hits = [w for w in (self.banned_placeholders or []) if w in blob_all]
        if ph_hits:
            reasons.append(f"出現 placeholder/佔位命名：{ph_hits[:3]}")

        pn_hits = [w for w in (self.banned_proper_nouns or []) if w in blob_all]
        if pn_hits:
            reasons.append(f"出現其他案例殘影/專有名詞：{pn_hits[:4]}")

        gamey_hits = [p for p in (self.gamey_patterns or []) if p in blob_all]
        if gamey_hits:
            reasons.append(f"出現對讀者下指令/遊戲提示句型：{gamey_hits[:4]}")

        # ✅ 全篇禁：幫讀者整理/記重點/排除
        hint_hits = [p for p in (self.banned_reader_hint_patterns or []) if p in blob_all]
        if hint_hits:
            reasons.append(f"出現『幫讀者整理/記重點/排除』句型：{hint_hits[:5]}")

        # ✅ 案件存在 gate
        if self.incident_node_id not in (nodes or {}):
            reasons.append(f"缺少案件節點：必須包含 {self.incident_node_id}")
        else:
            inc_text = self._node_narration(nodes, self.incident_node_id)
            if not inc_text.strip():
                reasons.append(f"{self.incident_node_id} narration 為空")

        # ✅ 事件延後 gate
        first_incident_nid = self._find_first_incident_node(nodes)
        if not first_incident_nid:
            reasons.append("未能定位事件發生節點（請確認有 scene_02_incident）")
        else:
            total_paras = self._count_total_paragraphs(nodes)
            before_paras = self._count_paragraphs_before_node(nodes, first_incident_nid)
            ratio = (before_paras / max(1, total_paras)) if total_paras > 0 else 0.0
            if (ratio < self.incident_min_ratio) and (before_paras < self.incident_min_paragraphs_before):
                reasons.append(
                    f"事件出現太早（首次出現在 {first_incident_nid}；before_paras={before_paras}, total={total_paras}, ratio={ratio:.2f} < {self.incident_min_ratio}）"
                )

        # final_accuse gate
        choices = self._final_accuse_choices(nodes)
        if not choices:
            reasons.append("final_accuse choices 缺失或格式不正確")
        else:
            if len(choices) != 4:
                reasons.append(f"final_accuse choices 必須剛好 4 個（目前 {len(choices)}）")
            else:
                if (choices[3] or "").strip() != self.unsure_choice_text.strip():
                    reasons.append(f"final_accuse 第 4 個選項必須完全等於：{self.unsure_choice_text}")

                suspects = [choices[0].strip(), choices[1].strip(), choices[2].strip()]
                if len(set(suspects)) != 3:
                    reasons.append(f"嫌疑人名字重複：{suspects}")

                pre_blob = self._pre_accuse_text_blob(nodes)
                for s in suspects:
                    if s and (s not in pre_blob):
                        reasons.append(f"嫌疑人未在指認前登場：{s}")

                fa = nodes.get("final_accuse")
                if isinstance(fa, dict):
                    si = fa.get("solution_index", None)
                    try:
                        si_int = int(si)
                    except Exception:
                        si_int = None
                    if si_int not in (0, 1, 2):
                        reasons.append(f"final_accuse.solution_index 必須是 0/1/2（目前：{si}）")

        # ✅ final_accuse narration 禁止「列舉嫌疑人/幫玩家整理」
        fa = nodes.get("final_accuse")
        if isinstance(fa, dict):
            fa_nar = str(fa.get("narration") or "")
            # 嫌疑人名字來自 choices[0..2]
            choices2 = self._final_accuse_choices(nodes)
            suspects2: list[str] = []
            if len(choices2) >= 3:
                suspects2 = [choices2[0].strip(), choices2[1].strip(), choices2[2].strip()]

            # (A) narration 內出現任何嫌疑人名字 → fail
            named_hits = [s for s in suspects2 if s and (s in fa_nar)]
            if named_hits:
                reasons.append(f"final_accuse narration 不得提到嫌疑人名字（命中：{named_hits}）")

            # (B) narration 出現「列舉/整理口吻」→ fail
            # ✅ 修正：避免把「最後時刻/最後一段」誤判成列舉
            # 只抓真的像在列舉（第一個/第二個/第三個/最後 +（一個/位/名/條/個/：））
            enum_regexes = [
                r"(第[一二三]個)\s*([一位名條個]|：|:)",
                r"(最後)\s*([一位名條個]|：|:)",
                r"(還有|另外|以及|再來)\s*([一位名條個]|：|:)",
                r"(可能是)\s*([一位名條個]|：|:)",
            ]
            enum_hits = []
            for pat in enum_regexes:
                if re.search(pat, fa_nar):
                    enum_hits.append(pat)
            if enum_hits:
                reasons.append(
                    "final_accuse narration 出現列舉/整理口吻（regex 命中）"
                )

        # 事件後搜尋 scene 數
        clue = self.clue_quality_report(nodes)
        if int(clue.get("scene_nodes_count") or 0) < self.min_scene_nodes_after_required:
            reasons.append(
                f"事件後搜尋/互動 scene 不足（{int(clue.get('scene_nodes_count') or 0)} < {self.min_scene_nodes_after_required}）"
            )

        if int(clue.get("distinct_objects") or 0) < 4:
            reasons.append("具體物件/痕跡種類不足（distinct_objects < 4）")

        # endings
        for eid in ("scene_10_ending_clear", "scene_10_ending_nudge", "scene_10_ending_defer"):
            nar = self._node_narration(nodes, eid)
            if not nar.strip():
                reasons.append(f"{eid} narration 為空")
                continue
            if not self._ending_ok(nar):
                reasons.append(f"{eid} 結尾不完整：必須包含『原因道歉教導』且至少 {self.ending_min_paragraphs} 段")

        return reasons

    def enrich_report(self, *, nodes: Dict[str, Any], theme: str) -> Dict[str, Any]:
        rep = {
            "theme": theme,
            "opening_paragraphs": self.opening_paragraphs(nodes),
            "clue": self.clue_quality_report(nodes),
            "style": self.style_quality_report(nodes),
        }
        rep["reasons"] = self.enrich_fail_reasons(nodes=nodes, theme=theme)
        return rep

    # ============================================================
    # Meta
    # ============================================================

    def ensure_case_id(self, meta: Dict[str, Any], forced_case_id: str | None) -> None:
        if forced_case_id:
            meta["case_id"] = forced_case_id
            return
        if not str(meta.get("case_id") or "").strip():
            meta["case_id"] = f"ai_{uuid.uuid4().hex[:10]}"

    # ============================================================
    # Prompt builders
    # ============================================================

    def json_skeleton(self) -> str:
        # ✅ 骨架：加入 warmup 節點，避免 scene_01_start 一口氣跳到 incident
        # ✅ 避免模型在 final_accuse 幫玩家整理嫌疑人
        return f"""
請只輸出 JSON（不要 markdown、不要 code fence、不要解釋）。
最外層只能有 meta, nodes。

{{
  "meta": {{
    "schema_version": "v1",
    "title": "故事標題",
    "tags": ["ai"]
  }},
  "nodes": {{
    "scene_01_start": {{
      "title": "開場：日常熱鬧",
      "narration": "至少 {self.opening_min_paragraphs} 段；用 \\n\\n 分段；每段 1~2 句；每段以 旁白：/霏霏：/樂樂：/大人：/老師：/店員：/爸爸：/媽媽： 開頭；只能日常互動/搞笑/配角登場；不要進事件",
      "choices": [{{"text":"繼續","next":"scene_01_warmup_2"}}]
    }},
    "scene_01_warmup_2": {{
      "title": "開場延伸：更多日常與配角",
      "narration": "至少 4 段；延續同一場景；加入新配角或小插曲；仍然只能日常搞笑；不要進事件；不要推理/可疑/調查",
      "choices": [{{"text":"再繼續","next":"scene_01_warmup_3"}}]
    }},
    "scene_01_warmup_3": {{
      "title": "好奇心轉場（小偵探模式）",
      "narration": "至少 4 段；最後 2~3 段必須是『好奇心轉場』：小孩俏皮、像要偷偷確認一下、眼睛亮亮、偵探模式/放大鏡模式；把故事自然帶到下一幕；❌ 禁止用『先繼續做原本的事/先繼續看書/先不管/算了先…』收尾",
      "choices": [{{"text":"我們去看看","next":"{self.incident_node_id}"}}]
    }},
    "{self.incident_node_id}": {{
      "title": "案件發生（中後段才開始）",
      "narration": "案件發生：用自然方式描述『今天出現一個需要弄清楚的狀況/衝突/事件』即可；用 \\n\\n 分段；不要講『開始調查/推理/真相』；保持日常尺度、無暴力",
      "choices": [{{"text":"一起看看發生什麼事","next":"scene_03_check_1"}}]
    }},
    "scene_03_check_1": {{
      "title": "第一個觀察",
      "narration": "至少 4 段；去一個地方看；每段要有具體物件/痕跡或行為；不要說『這是線索/記住』",
      "choices": [{{"text":"再找找看","next":"scene_04_check_2"}}]
    }},
    "scene_04_check_2": {{
      "title": "第二個觀察",
      "narration": "至少 4 段；換另一個地點或角度；加入新的具體物件/痕跡；允許小誤會或吐槽，但不要替讀者下結論",
      "choices": [{{"text":"換個地方看看","next":"scene_05_check_3"}}]
    }},
    "scene_05_check_3": {{
      "title": "第三個觀察（可誤導但不強制排除）",
      "narration": "至少 6 段；要有新的具體物件/痕跡；可以出現一個誇張或好笑的『假線索/誤會』，但不必明確排除；絕對不要出現『幫你整理重點/請記住/線索總結/因此排除』",
      "choices": [{{"text":"我有一個猜想","next":"scene_06_hypothesis_1"}}]
    }},
    "scene_06_hypothesis_1": {{
      "title": "猜想（不下結論）",
      "narration": "至少 4 段；只能用『可能/也許/我在想』這種不確定語氣；霏霏偏吐槽/陪玩，不暗示答案；不要替讀者整理",
      "choices": [{{"text":"我要指認","next":"final_accuse"}}]
    }},
    "final_accuse": {{
      "title": "誰可能和這件事有關呢？",
      "narration": "只能是短導語（2~4 段）：提醒要選了 + 俏皮鼓勵（偵探模式）+ 告訴孩子也可以選『{self.unsure_choice_text}』；❌ 禁止列舉嫌疑人名字與理由；❌ 禁止回顧線索",
      "choices": [
        {{"text":"嫌疑人1","next":"scene_10_ending_clear"}},
        {{"text":"嫌疑人2","next":"scene_10_ending_nudge"}},
        {{"text":"嫌疑人3","next":"scene_10_ending_defer"}},
        {{"text":"{self.unsure_choice_text}","next":"scene_10_ending_defer"}}
      ],
      "solution_index": 0
    }},
    "scene_10_ending_clear": {{
      "title": "結尾（推理正確）",
      "narration": "...（原因/道歉/教導/餘韻；至少 {self.ending_min_paragraphs} 段；必須有大人溫和介入收尾）",
      "choices": [{{"text":"故事結束","next":"quit"}}]
    }},
    "scene_10_ending_nudge": {{
      "title": "結尾（差一點）",
      "narration": "...（原因/道歉/教導；至少 {self.ending_min_paragraphs} 段；必須有大人溫和介入收尾）",
      "choices": [{{"text":"故事結束","next":"quit"}}]
    }},
    "scene_10_ending_defer": {{
      "title": "結尾（交給大人）",
      "narration": "...（原因/道歉/教導；至少 {self.ending_min_paragraphs} 段；必須有大人溫和介入收尾；包含『不確定也沒關係』的收束）",
      "choices": [{{"text":"故事結束","next":"quit"}}]
    }},
    "quit": {{
      "title": "結束",
      "narration": "旁白：故事先到這裡，謝謝你一起當小偵探！",
      "choices": [],
      "can_replay": true,
      "can_quit": true
    }}
  }}
}}
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
        instructions = self.build_instructions(include_old_rival=include_old_rival)
        style = extract_style_example()
        seed_line = f"{int(seed)}" if seed is not None else "null"

        opening_banned_all = self._opening_banned_all()
        reader_hint_banned = self.banned_reader_hint_patterns or []

        # 結尾關鍵字（硬性要求，對齊 _ending_ok 的 gate）
        ending_reason_kw = "因為/所以/原來/其實是"
        ending_apology_kw = "對不起/抱歉/道歉"
        ending_teach_kw = "下次/以後/記得/學到/提醒"

        prompt = f"""
{rules_text}

{instructions}

你是一位「故事型偵探推理遊戲」的兒童故事作家，要寫給小一能懂、好笑、有日常感（霏霏＆樂樂）。

【最重要的 9 件事（必須全部遵守）】
1) scene_01_start 是純日常開場（鋪陳/互動/搞笑/配角登場），至少 {self.opening_min_paragraphs} 段（\\n\\n 分段）。
2) ✅ scene_01_start 內「任何字串位置」都不得出現禁詞（包含引號、括號、轉述、任何角色台詞）：
   {", ".join(opening_banned_all)}
3) ✅ 開頭前 3 段要交代「在哪裡、在做什麼、有哪些人（至少 2 位配角）」。
4) ✅ scene_01_start（或 warmup 最後一幕）的最後 2～3 段必須是「好奇心轉場」：
   - 語氣：小孩俏皮、像要偷偷用眼睛確認一下（例如：小聲偵探模式/放大鏡模式/眼睛亮亮）
   - 目的：把故事自然帶到下一幕（案件節點）但不要緊張、不要嚴肅
   - ❌ 禁止用「先繼續做原本的事」來收尾，例如：先繼續看書/先不管/算了我們先…（會突兀）
5) ✅ 必須存在案件節點：{self.incident_node_id}
   - 案件形式不限：只要清楚表達「今天發生了一件需要弄清楚的事」就算案件成立（不用硬套失竊/不見）。
6) ✅ 事件必須延後：{self.incident_node_id} 應該在故事約 40% 之後才出現（前面都在日常搞笑）。
7) ✅ 全篇禁止「幫讀者整理線索/重點回顧/請記住/因此排除/結論是…」這種口吻（孩子要自己觀察與記住）：
   {", ".join(reader_hint_banned)}
   - 允許偶爾出現很離譜的誤會被吐槽，但不要每次都強制排除、更不要做「總結條列」。
8) ✅ final_accuse 的 narration 只能是「短導語」（建議 2～4 段）：
   - 只能做：提醒要選了 + 俏皮鼓勵（可提“偵探模式”）+ 告訴孩子也可以選「{self.unsure_choice_text}」
   - ❌ 禁止在 final_accuse.narration 內列舉三個嫌疑人（含名字/含列舉語氣）或給理由（不要代替推理）
9) ✅ 結尾三段（clear/nudge/defer）都要完整：原因 + 道歉 + 教導，且至少 {self.ending_min_paragraphs} 段；必須有大人溫和介入收尾。
   - 強制段落定位（最穩過 gate）：
     第 2 段【原因】必須包含：{ending_reason_kw}
     第 4 段【道歉】必須包含：{ending_apology_kw}
     第 5 段【教導】必須包含：{ending_teach_kw}
   - 原因/道歉/教導 不要寫在同一段，分段更穩。

【場景】
- 本次場景建議：{theme if theme else "由你自由決定（安全、日常尺度）"}

【指認】
- final_accuse 必須 4 個選項，且第 4 個必須完全等於：{self.unsure_choice_text}
- solution_index 只能 0/1/2

【禁止對讀者下指令】
- 不要出現：{", ".join(self.gamey_patterns or [])}

【輸出格式】
- 只輸出 JSON object（不要 markdown / code fence）
- 最外層只能有 meta, nodes
- narration 用 \\n\\n 分段，每段用「角色：內容」開頭（旁白/霏霏/樂樂/老師/大人/店員/爸爸/媽媽）

{self.json_skeleton()}

【節奏錨點 A（只學節奏，不得照抄）】
{GOLDEN_OPENING_EXAMPLE}

【節奏錨點 B（只學語氣/段落，不得照抄）】
{style}

seed={seed_line}
nonce={nonce}

最後提醒：只輸出 JSON object。
"""
        return textwrap.dedent(prompt).strip()

    # ============================================================
    # Repair
    # ============================================================

    def build_repair_prompt(self, *, raw_text: str, error: str, theme: str) -> str:
        """
        repair 的唯一目標：讓 validator 過。

        ✅ 兩種常見 repair：
        A) 開場段落不足：append-only 補到剛好 N 段
        B) 開場命中禁詞：不要做同義詞替換，改成「替換整個命中段落（\\n\\n 分段）」
        """
        style = extract_style_example()

        m_paras = re.search(
            r"scene_01_start\.narration\s*至少\s*(\d+)\s*段，\s*目前\s*(\d+)\s*段",
            (error or ""),
        )

        opening_banned_all = self._opening_banned_all()
        opening_banned_text = "、".join(opening_banned_all) if opening_banned_all else "(none)"

        safe_patterns = "\n".join([f"- {s}" for s in (self.opening_safe_patterns or [])])

        # A) 開場段落不足 → append-only
        if m_paras:
            min_need = int(m_paras.group(1))
            cur = int(m_paras.group(2))
            add_n = max(0, min_need - cur)
            return f"""
你上一版 JSON 沒通過驗證：scene_01_start 段落不足。

# 驗證錯誤
{error}

theme={theme}

【絕對規則】
- 只輸出完整 JSON object（不要 markdown / code fence / 解釋）
- 最外層只能有 meta, nodes
- 只允許修改：nodes.scene_01_start.narration
- 只允許追加段落（append only），禁止刪除/改寫既有段落，禁止改其他任何節點

【追加目標】
- 目前段落數={cur}
- 必須追加段落數={add_n}
- 追加後必須剛好={min_need} 段（用 \\n\\n 分段計數）
- 追加段落仍必須完全不包含任何開場禁詞（包含引號/轉述/台詞）：{opening_banned_text}

【可學的安全句型示範（只學語氣/節奏，不可照抄）】
{safe_patterns}

【節奏錨點（只學節奏，不得照抄）】
{GOLDEN_OPENING_EXAMPLE}

【你要修補的 JSON（請就地追加後輸出完整 JSON）】
{raw_text}
""".strip()

        # B) 開場命中禁詞 → “替換段落”模式
        banned_word = ""
        m = re.search(r"\[scene_01_start\]\s*出現禁止詞：(.+)$", (error or "").strip())
        if m:
            banned_word = (m.group(1) or "").strip()

        offending_paras: List[str] = []
        try:
            obj = json.loads(raw_text)
            nodes = obj.get("nodes") if isinstance(obj, dict) else None
            s1 = nodes.get("scene_01_start") if isinstance(nodes, dict) else None
            nar = s1.get("narration") if isinstance(s1, dict) else None
            if isinstance(nar, str):
                paras = self.split_paragraphs(nar)
                for p in paras:
                    hits = []
                    if banned_word and (banned_word in p):
                        hits = [banned_word]
                    else:
                        hits = self._has_any_opening_banned(p)
                    if hits:
                        offending_paras.append(p)
        except Exception:
            pass

        offending_block = (
            "\n\n".join([f"【命中段落示例】\n{x}" for x in offending_paras[:2]])
            if offending_paras
            else "（未能自動擷取命中段落，你需要自行在 scene_01_start 的 \\n\\n 段落中找出含禁詞的段落）"
        )

        return f"""
你上一版 JSON 沒通過驗證：scene_01_start 命中開場禁詞。
這次不要做同義詞替換，請用「替換段落」的方式修好。

# 驗證錯誤
{error}

theme={theme}

【絕對規則】
- 只輸出完整 JSON object（不要 markdown / code fence / 解釋）
- 最外層只能有 meta, nodes
- 只允許修改：nodes.scene_01_start.narration
- 其他 nodes 完全不動（不要改 title/choices/節點 id/嫌疑人名字）

【你要做的事（一定照做）】
1) 把 scene_01_start.narration 用 \\n\\n 分段
2) 找出「包含任何開場禁詞」的段落（包含引號/括號/轉述/台詞）
3) 對每個命中段落：直接用「全新的一段」替換它（不是修句子）
   - 替換後段落仍需是日常/互動/搞笑/配角登場（不可進入事件、不可推理）
   - 每段 1~2 句
   - 每段仍要用「旁白：/霏霏：/樂樂：/老師：/大人：/店員：/爸爸：/媽媽：」開頭
4) 替換完成後，再逐字掃描整個 scene_01_start，確保完全不含禁詞：
   {opening_banned_text}

【可學的安全句型示範（只學語氣/節奏，不可照抄）】
{safe_patterns}

【系統擷取到的命中段落（供你定位；若沒有就自己找）】
{offending_block}

【節奏錨點（只學節奏，不得照抄）】
{GOLDEN_OPENING_EXAMPLE}

【語氣錨點（只學語氣/段落，不得照抄）】
{style}

【你要修補的 JSON（請就地替換段落後輸出完整 JSON）】
{raw_text}
""".strip()

    # ============================================================
    # Enrich helpers
    # ============================================================

    def _extract_scene01_offending_paras(self, raw_json: str) -> Dict[str, Any]:
        """
        給 enrich_prompt 用：把 scene_01_start 命中禁詞的段落抓出來，讓模型「替換段落」而不是亂改全篇。
        回傳：
          {
            "hits": ["走散", ...],
            "offending_paras": ["段落原文", ...]
          }
        """
        hits: List[str] = []
        offending: List[str] = []
        try:
            obj = json.loads(raw_json)
            nodes = obj.get("nodes") if isinstance(obj, dict) else None
            s1 = nodes.get("scene_01_start") if isinstance(nodes, dict) else None
            nar = s1.get("narration") if isinstance(s1, dict) else None
            if isinstance(nar, str) and nar.strip():
                paras = self.split_paragraphs(nar)
                banned_all = self._opening_banned_all()
                for p in paras:
                    phits = [w for w in banned_all if w and (w in p)]
                    if phits:
                        hits.extend(phits)
                        offending.append(p)
        except Exception:
            pass

        hits = list(dict.fromkeys([h for h in hits if h]))
        offending = offending[:3]
        return {"hits": hits, "offending_paras": offending}

    # ============================================================
    # Enrich
    # ============================================================

    def build_enrich_prompt(self, *, raw_json: str, theme: str, rep: Dict[str, Any]) -> str:
        """
        enrich：只針對 reasons 指到的點做最小修改，不要重寫整篇。

        ✅ 特別針對 ending 不完整：
        - 用「6 段骨架」讓 AI 更穩過 gate
        - 並允許插入搞笑/互動（放在骨架指定位置）

        ✅ 特別針對 scene_01_start 禁詞：
        - 把命中段落抓出來，要求「整段替換」（不要同義詞替換），避免 enrich 卡住不修乾淨
        """
        style = extract_style_example()
        reasons = rep.get("reasons") or []
        reasons_text = "\n".join([f"- {r}" for r in reasons]) if reasons else "- (none)"

        opening_banned_all = self._opening_banned_all()
        reader_hint_banned = self.banned_reader_hint_patterns or []

        # ✅ 若理由含 scene_01_start 禁詞：提供命中段落，要求「替換段落」
        need_fix_scene01_banned = any(
            isinstance(r, str) and ("scene_01_start" in r and "開場禁詞" in r) for r in reasons
        )
        s01_fix_block = ""
        if need_fix_scene01_banned:
            info = self._extract_scene01_offending_paras(raw_json)
            hits = info.get("hits") or []
            offending_paras = info.get("offending_paras") or []
            offending_text = (
                "\n\n".join([f"【命中段落】\n{p}" for p in offending_paras])
                if offending_paras
                else "（未擷取到命中段落，請你自行找出含禁詞的段落）"
            )
            s01_fix_block = f"""
【scene_01_start 禁詞修補（必做）】
- 你只允許修改：nodes.scene_01_start.narration
- 修法：用 \\n\\n 分段後，找出包含禁詞的段落，對每個命中段落「整段替換」成全新的一段（不要在原句上做同義詞替換）
- 替換後仍然只能是日常互動/玩笑/配角登場，不要進事件、不推理、不緊張
- 修補後請自己逐字掃描一次，確保命中數 = 0

命中的禁詞（供你對照）：{", ".join(hits) if hits else "(unknown)"}

系統擷取到的命中段落（供你定位）：
{offending_text}
""".strip()

        need_endings: List[str] = []
        for eid in ("scene_10_ending_clear", "scene_10_ending_nudge", "scene_10_ending_defer"):
            for r in reasons:
                if eid in r:
                    need_endings.append(eid)
                    break
        need_endings = list(dict.fromkeys(need_endings))

        ending_focus = ""
        if need_endings:
            ending_focus = f"""
【本次結尾修補指令（最重要）】
- 你只需要修改以下 ending 節點的 narration（其他節點不動）：{", ".join(need_endings)}
- 每個被修的 ending narration 必須用 \\n\\n 分成「至少 {self.ending_min_paragraphs} 段」
- 強烈建議用固定骨架（每段 1~2 句，短短就好）：
  1) 收尾情境（大家回到安全、有人協助）
  2) 原因（必須含：因為/所以/原來/其實是 其中之一）
  3) 搞笑/互動（霏霏吐槽、樂樂誇張，或配角插話；但不要破壞事件事實）
  4) 道歉（必須含：對不起/抱歉/道歉 其中之一）
  5) 教導（必須含：下次/以後/記得/學到/提醒 其中之一）
  6) 餘韻（和好、回到日常、結尾暖暖的）
- 注意：原因 / 道歉 / 教導 這三件事「不要省略」，最好分開段落寫，最穩。
""".strip()

        return f"""
你是「故事 JSON 修補師」。目標是：用最小修改把 JSON 修到通過 gate。

theme={theme}

【絕對規則】
- 只輸出完整 JSON object（不要 markdown / code fence / 解釋）
- 不要重寫整篇：只針對 reasons 指到的點修
- 若 scene_01_start 已經 >= {self.opening_min_paragraphs} 段：禁止再加長開場
- 保持單一主題，不要換場景

【本次 gate 失敗原因（逐條修掉）】
{reasons_text}

【提醒：開場禁詞（scene_01_start 任何位置都不得出現，包含引號/轉述/台詞）】
{", ".join(opening_banned_all)}

{s01_fix_block}

【全篇禁止（孩子自己判斷/記住，不要替讀者總結排除）】
{", ".join(reader_hint_banned)}

【事件延後】
- 事件節點 {self.incident_node_id} 必須在故事約 40% 才出現（前面都在日常搞笑）

{ending_focus}

【禁止對讀者下指令】
- 不要出現：{", ".join(self.gamey_patterns or [])}

【節奏錨點（只學節奏，不得照抄）】
{GOLDEN_OPENING_EXAMPLE}

【語氣錨點（只學語氣/段落，不得照抄）】
{style}

【你要修補的 JSON（請就地修改後輸出完整 JSON）】
{raw_json}
""".strip()
