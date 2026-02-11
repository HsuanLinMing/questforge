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
    ✅ 以 story_writer_cli 的思路為主：
    - 用規範 + 節奏錨點 + 明確驗證規則「教 AI 怎麼寫」
    - 不在這裡做大量替換/寫死對話/改寫 AI 內容
    - runtime 若驗證失敗 → 用 repair/enrich prompt 讓 AI 自己修
    """

    prompts_dir: Path = Path("src/questforge/ai/prompts")

    # runtime instruction files（跟 CLI 概念一致；不含 template，避免引導成 Python 檔）
    core_files: List[str] = None  # set in __post_init__

    # 固定的不確定選項文字（UI/合約一致）
    unsure_choice_text: str = "我還不確定，交給大人"

    # 開場段落數要求（用「段落」：以 \n\n 分段）
    opening_min_paragraphs: int = 22

    # 事件後至少要有幾個「自然搜尋」scene（避免事件一出就指認）
    min_scene_nodes_after_required: int = 2

    # ✅ 事件詞（允許出現，但必須延後到故事約 40% 之後才第一次出現）
    incident_terms: List[str] = None  # set in __post_init__
    incident_min_ratio: float = 0.40
    incident_min_paragraphs_before: int = 16  # ratio 之外的保底（避免短篇誤判）

    # ✅ 結尾完整性（原因 + 道歉 + 教導）最少段落
    ending_min_paragraphs: int = 6

    # 允許的背景主題集合（由 runtime pick theme）
    # ✅ 改成可選：None 代表不限制
    allowed_background_themes: Optional[List[str]] = None  # set in __post_init__

    # cases 殘影（避免帶到別案名詞）
    banned_proper_nouns: List[str] = None  # set in __post_init__

    # 開場禁止詞（注意：不含 incident_terms）
    forbidden_opening_terms: List[str] = None  # set in __post_init__

    # 禁止 placeholder 命名（跟 CLI validator 一致）
    banned_placeholders: List[str] = None  # set in __post_init__

    # 禁止泛稱（要求配角要有名字）
    banned_generics: List[str] = None  # set in __post_init__

    # 禁止「遊戲提示」口吻（不要對讀者說「你會怎麼做」）
    gamey_patterns: List[str] = None  # set in __post_init__

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
            # ✅ 預設給很大的日常場景池（想用就用），但 prompt 不再強制必須從這裡選
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
            self.banned_proper_nouns = ["千羽會", "亨利爵士", "孔雀", "喵喵（粉絲）", "老鷹大翔"]

        # ✅ 事件詞：允許出現，但不得在開場出現，且首次出現需延後
        if self.incident_terms is None:
            self.incident_terms = [
                "不見",
                "找不到",
                "遺失",
                "被偷",
                "消失",
                "失蹤",
            ]

        # ✅ 開場禁止詞：只禁「異常/推理/案件口吻」，不包含 incident_terms
        if self.forbidden_opening_terms is None:
            self.forbidden_opening_terms = [
                "可疑",
                "奇怪",
                "不尋常",
                "發現問題",
                "出事",
                "有問題",
                "開始調查",
                "推理過程",
                "解決案件",
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
            self.banned_generics = ["紅色衣服", "那個男孩", "某位同學", "穿外套的人", "小朋友"]

        if self.gamey_patterns is None:
            self.gamey_patterns = [
                "你覺得該怎麼辦",
                "你會怎麼做",
                "請選擇",
                "玩家",
                "如果你在這裡",
                "你覺得呢",
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
    # Light text helpers (不改寫內容，只做分析/檢查)
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

    # ============================================================
    # Quality report / gate（只產生報告，不改寫內容）
    # ============================================================

    def clue_quality_report(self, nodes: Dict[str, Any]) -> Dict[str, Any]:
        blob = self.collect_narration_text(nodes)

        object_keywords = [
            "貼紙",
            "背紙",
            "膠帶",
            "雙面膠",
            "標籤",
            "便條",
            "紙屑",
            "印記",
            "墨水",
            "票",
            "卡",
            "號碼牌",
            "抽籤筒",
            "籤",
            "袋子",
            "背包",
            "盒子",
            "收納盒",
            "透明袋",
            "拉鍊",
            "扣環",
            "水漬",
            "粉末",
            "碎屑",
            "刮痕",
            "掉落",
            "裂痕",
            "味道",
            "香味",
            "刺鼻",
            "黏黏",
            "滑滑",
            "濕濕",
        ]
        hits = 0
        distinct = 0
        for kw in object_keywords:
            c = blob.count(kw)
            if c > 0:
                hits += c
                distinct += 1

        generic_phrases = [
            "我們找到線索了",
            "這一定是線索",
            "關鍵線索",
            "真相只有一個",
            "就是這個了",
            "這很明顯",
            "毫無疑問",
        ]
        generic_hits = sum(blob.count(g) for g in generic_phrases)

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
            "object_hits": min(hits, 199),
            "distinct_objects": distinct,
            "generic_hits": generic_hits,
            "scene_nodes_count": len(scene_nodes),
        }

    def style_quality_report(self, nodes: Dict[str, Any]) -> Dict[str, Any]:
        blob = self.collect_narration_text(nodes)

        second_person_hits = 0
        for p in self.gamey_patterns:
            if p in blob:
                second_person_hits += blob.count(p)

        paras = [x.strip() for x in blob.split("\n\n") if x.strip()]
        seen: set[str] = set()
        dup = 0
        for p in paras:
            key = re.sub(r"\s+", "", p)
            if len(key) < 12:
                continue
            if key in seen:
                dup += 1
            else:
                seen.add(key)

        return {"second_person_hits": second_person_hits, "dup_paragraphs": dup}

    def needs_enrich(self, *, nodes: Dict[str, Any]) -> bool:
        if self.opening_paragraphs(nodes) < self.opening_min_paragraphs:
            return True

        clue = self.clue_quality_report(nodes)
        style = self.style_quality_report(nodes)

        if int(clue.get("scene_nodes_count") or 0) < self.min_scene_nodes_after_required:
            return True

        if int(clue.get("distinct_objects") or 0) < 4:
            return True
        if int(clue.get("generic_hits") or 0) >= 2:
            return True

        if int(style.get("second_person_hits") or 0) >= 1:
            return True

        if int(style.get("dup_paragraphs") or 0) > 2:
            return True

        # ✅ incident / ending gate 也會導致 enrich
        rep = self.enrich_report(nodes=nodes, theme="(n/a)")
        if rep.get("reasons"):
            return True

        return False

    # ============================================================
    # Enrich gate (CLI-like checks, report only; no rewriting)
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

    # ----------------------------
    # Incident position helpers
    # ----------------------------

    def _node_narration(self, nodes: Dict[str, Any], nid: str) -> str:
        node = (nodes or {}).get(nid)
        if isinstance(node, dict):
            nar = node.get("narration")
            if isinstance(nar, str):
                return nar
        return ""

    def _ordered_node_ids(self, nodes: Dict[str, Any]) -> List[str]:
        # Python dict preserve insertion order; runtime 生成通常也是依順序建
        return list((nodes or {}).keys())

    def _find_first_incident_node(self, nodes: Dict[str, Any]) -> Optional[str]:
        for nid in self._ordered_node_ids(nodes):
            nar = self._node_narration(nodes, nid)
            if nar and any(t in nar for t in self.incident_terms):
                return nid
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

    # ----------------------------
    # Ending completeness
    # ----------------------------

    def _ending_ok(self, text: str) -> bool:
        t = text or ""
        has_reason = any(k in t for k in ["因為", "所以", "原來", "其實是"])
        has_apology = any(k in t for k in ["對不起", "道歉", "抱歉"])
        has_teach = any(k in t for k in ["下次", "以後", "記得", "學到", "提醒"])
        paras = len(self.split_paragraphs(t))
        return has_reason and has_apology and has_teach and paras >= self.ending_min_paragraphs

    def enrich_fail_reasons(self, *, nodes: Dict[str, Any], theme: str) -> List[str]:
        reasons: List[str] = []

        # --- scene_01_start 基本檢查 ---
        s01 = self._scene01_text(nodes)
        if not s01.strip():
            reasons.append("scene_01_start narration 為空")
        else:
            open_paras = len(self.split_paragraphs(s01))
            if open_paras < self.opening_min_paragraphs:
                reasons.append(f"scene_01_start 段落不足（{open_paras} < {self.opening_min_paragraphs}）")

            # ✅ 開場禁止：異常/推理口吻
            hits = [w for w in self.forbidden_opening_terms if w in s01]
            if hits:
                reasons.append(f"scene_01_start 出現禁止詞（異常/推理口吻）：{hits}")

            # ✅ 開場禁止：事件詞（必須延後）
            open_incident_hits = [w for w in self.incident_terms if w in s01]
            if open_incident_hits:
                reasons.append(
                    f"scene_01_start 出現事件詞（必須延後到 40% 之後才可首次出現）：{open_incident_hits}"
                )

            if self._has_kana(s01):
                reasons.append("scene_01_start 出現日文假名（平假名/片假名）")

            gen_hits = [w for w in self.banned_generics if w in s01]
            if gen_hits:
                reasons.append(f"scene_01_start 出現泛稱（請改成有名字的配角）：{gen_hits}")

        # --- placeholder 命名（全故事） ---
        blob_all = self._all_text(nodes)
        ph_hits = [w for w in self.banned_placeholders if w in blob_all]
        if ph_hits:
            reasons.append(f"出現 placeholder/佔位命名：{ph_hits[:3]}")

        # --- 其他案例殘影（全故事） ---
        pn_hits = [w for w in self.banned_proper_nouns if w in blob_all]
        if pn_hits:
            reasons.append(f"出現其他案例殘影/專有名詞：{pn_hits[:4]}")

        # --- 遊戲提示口吻（全故事） ---
        gamey_hits = [p for p in self.gamey_patterns if p in blob_all]
        if gamey_hits:
            reasons.append(f"出現對讀者下指令/遊戲提示句型：{gamey_hits[:4]}")

        # --- ✅ 事件詞延後 40% gate（全故事） ---
        first_incident_nid = self._find_first_incident_node(nodes)
        if not first_incident_nid:
            reasons.append(f"全故事未出現事件詞（需在中後段明確發生事件）：{self.incident_terms}")
        else:
            total_paras = self._count_total_paragraphs(nodes)
            before_paras = self._count_paragraphs_before_node(nodes, first_incident_nid)
            ratio = (before_paras / max(1, total_paras)) if total_paras > 0 else 0.0
            if (ratio < self.incident_min_ratio) and (before_paras < self.incident_min_paragraphs_before):
                reasons.append(
                    f"事件出現太早（首次出現在 {first_incident_nid}；before_paras={before_paras}, total={total_paras}, ratio={ratio:.2f} < {self.incident_min_ratio}）"
                )

        # --- final_accuse choices（4個 + 第4固定 + 前三是名字且在前文出現） ---
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
                for s in suspects:
                    if not s:
                        reasons.append("final_accuse 前三個嫌疑人名字不可為空")
                        break
                    if "老師" in s or "不確定" in s or "交給" in s:
                        reasons.append(f"final_accuse 前三個選項必須是名字（目前：{s}）")
                        break
                    if any(ph in s for ph in self.banned_placeholders):
                        reasons.append(f"嫌疑人名字出現 placeholder：{s}")
                        break

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

        # --- 事件後 scene 數 ---
        clue = self.clue_quality_report(nodes)
        if int(clue.get("scene_nodes_count") or 0) < self.min_scene_nodes_after_required:
            reasons.append(
                f"事件後搜尋/互動 scene 不足（{int(clue.get('scene_nodes_count') or 0)} < {self.min_scene_nodes_after_required}）"
            )

        # --- 線索自然度 ---
        if int(clue.get("distinct_objects") or 0) < 4:
            reasons.append("具體物件/痕跡種類不足（distinct_objects < 4）")
        if int(clue.get("generic_hits") or 0) >= 2:
            reasons.append("模板線索句過多（generic_hits >= 2）")

        # --- ✅ endings 完整性（原因+道歉+教導）---
        for eid in ("scene_10_ending_clear", "scene_10_ending_nudge", "scene_10_ending_defer"):
            nar = self._node_narration(nodes, eid)
            if not nar.strip():
                reasons.append(f"{eid} narration 為空")
                continue
            if not self._ending_ok(nar):
                reasons.append(
                    f"{eid} 結尾不完整：必須明確包含『原因+道歉+教導』且至少 {self.ending_min_paragraphs} 段（\\n\\n 分段）"
                )

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
    # Prompt builders（關鍵：像 story_writer_cli 一樣「教 AI 怎麼寫」）
    # ============================================================

    def json_skeleton(self) -> str:
        return f"""
請只輸出 JSON（不要 markdown、不要 code fence、不要解釋）。
最外層只能有 meta + nodes。

{{
  "meta": {{
    "schema_version": "v1",
    "title": "故事標題",
    "tags": ["ai"]
  }},
  "nodes": {{
    "scene_01_start": {{
      "title": "...",
      "narration": "至少 {self.opening_min_paragraphs} 段；用 \\n\\n 分段；每段 1~2 句；以 旁白：/霏霏：/樂樂：/大人： 開頭（需要時可用 爸爸：/媽媽：/店員：/警察：/老師：）",
      "choices": [{{"text":"繼續聽故事","next":"（必須存在節點）"}}]
    }},
    "final_accuse": {{
      "title": "...",
      "narration": "...",
      "choices": [
        {{"text":"嫌疑人1","next":"scene_10_ending_clear"}},
        {{"text":"嫌疑人2","next":"scene_10_ending_nudge"}},
        {{"text":"嫌疑人3","next":"scene_10_ending_defer"}},
        {{"text":"{self.unsure_choice_text}","next":"scene_10_ending_defer"}}
      ],
      "solution_index": 0
    }},
    "scene_10_ending_clear": {{
      "title": "...",
      "narration": "...（原因+道歉+修復+教導+餘韻；至少 {self.ending_min_paragraphs} 段）",
      "choices": [{{"text":"故事結束","next":"quit"}}]
    }},
    "scene_10_ending_nudge": {{
      "title": "...",
      "narration": "...（差一點：霏霏補一句 + 老師補齊；含原因+道歉+教導；至少 {self.ending_min_paragraphs} 段）",
      "choices": [{{"text":"故事結束","next":"quit"}}]
    }},
    "scene_10_ending_defer": {{
      "title": "...",
      "narration": "...（不指認：交給大人確認 + 安全收尾；含原因+道歉+教導；至少 {self.ending_min_paragraphs} 段）",
      "choices": [{{"text":"故事結束","next":"quit"}}]
    }},
    "quit": {{
      "title": "...",
      "narration": "...",
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

        return f"""
{rules_text}

{instructions}

你是一位「故事型偵探推理遊戲」的兒童故事作家。
你要寫的是：給小一能懂、好笑、有日常感的偵探故事（霏霏＆樂樂）。

────────────────
【硬性生成要求（非常重要，務必遵守）】

1) 結構完整性（缺一不可）
- 必須包含並完整定義以下 nodeId（不可缺漏）：
  - scene_01_start
  - final_accuse
  - scene_10_ending_clear
  - scene_10_ending_nudge
  - scene_10_ending_defer
  - quit
- 每個 ending 節點必須含：
  - title
  - narration（必須『原因+道歉+修復+教導+餘韻』，不可只有一句話；至少 {self.ending_min_paragraphs} 段）
  - choices: [{{"text":"故事結束","next":"quit"}}]
- quit 節點必須包含 can_replay 與 can_quit

2) 開場硬規範
- scene_01_start 必須像「真正的故事第一章」，至少 {self.opening_min_paragraphs} 段 narration（用 \\n\\n 分段）
- scene_01_start 只能做：世界觀介紹 / 日常互動 / 玩笑吐槽 / 配角登場
- scene_01_start 禁止「異常/推理口吻」：{", ".join(self.forbidden_opening_terms)}
- scene_01_start 禁止「事件詞」：{", ".join(self.incident_terms)}
  - ✅ 允許寫「老師要宣布一件重要事」「大家有點慌但先忙著準備」「箱子被挪動」「有人皺眉在找」等
  - ❌ 不可直接寫「不見/遺失/被偷/找不到/消失」
- 禁止日文（不得出現平假名/片假名）

3) ✅ 事件詞延後規則（非常重要）
- 事件詞：{", ".join(self.incident_terms)}
- 必須在故事約 40% 之後才第一次出現（前段只能鋪陳與互動）
- 但中後段必須明確出現至少一次，故事才能成立

4) 角色命名硬規則（禁止 placeholder / 泛稱）
- 配角必須有名字：禁止泛稱（例如：{", ".join(self.banned_generics)}）
- 禁止 placeholder/佔位命名（例如：{", ".join(self.banned_placeholders)}）

5) 指認候選人硬規則（final_accuse）
- final_accuse 必須剛好 4 個選項：
  (1) 嫌疑人1（可愛命名）
  (2) 嫌疑人2（可愛命名）
  (3) 嫌疑人3（可愛命名）
  (4) 必須 **完全等於**：{self.unsure_choice_text}
- 前三個只允許「名字」，不可夾帶句子
- 前三個嫌疑人名字必須在前文（scene_01_start～指認前）明確登場過至少一次
- final_accuse 必須包含 solution_index: 0/1/2（只能指向前三個嫌疑人之一；不可是 3）

6) 中段搜尋節奏（避免太快指認）
- 事件出現後，必須至少有 2～3 個連續 scene 在做「自然搜尋」：
  - 回到剛剛的位置對照 / 問不同人 / 看物品痕跡 / 被打斷 / 再次確認
- 不可「事件一出就立刻指認」

7) 場景自由（不限校園，但要安全、日常尺度）
- 背景場景可以是任何「兒童安全、日常尺度」地點（校園/公園/商店/車站/博物館/夜市/社區活動…都可以）
- 故事開頭前 3 段內要明確交代「我們在哪裡、在做什麼」
- 本次場景建議：{theme if theme else "（由你自由決定）"}

8) 禁止遊戲提示口吻（不要對讀者下指令）
- 禁止句型：{", ".join(self.gamey_patterns)}
- 你可以讓角色彼此提問（？），但不要問讀者選什麼

9) 範例只學節奏，不可照抄內容
- 你要模仿「節奏/口吻/段落感」
- 不可沿用任何專有名詞或舊案殘影（例如：{", ".join(self.banned_proper_nouns)}）

────────────────
【輸出格式（必須遵守）】
- 只輸出一個 JSON object
- 最外層只能有 meta + nodes
- narration 用 \\n\\n 分段，且每段用「角色：內容」開頭（旁白/霏霏/樂樂/老師）
- 禁止任何 markdown / code fence

{self.json_skeleton()}

────────────────
【節奏錨點 A（只學節奏，不得照抄）】
{GOLDEN_OPENING_EXAMPLE}

────────────────
【節奏錨點 B（只學語氣/段落，不得照抄）】
{style}

────────────────
【案件 seed（僅作背景，不代表劇情順序）】
seed={seed_line}
nonce={nonce}

最後提醒：只輸出 JSON object。
""".strip()

    def build_repair_prompt(self, *, raw_text: str, error: str, theme: str) -> str:
        style = extract_style_example()
        return f"""
你上一版 JSON 沒有通過驗證。請你「保持故事內容與人物盡量不變」，只做必要修補（最小修改）。

# 驗證錯誤
{error}

# 本次主題（必須維持單一主題）
theme={theme}

# 修補規則
- 你必須輸出「完整 JSON object」（不要 markdown、不要 code fence、不要解釋）
- 只修正：缺漏欄位、違規文字、結構不合規
- 不可用 placeholder 命名，不可用泛稱
- 第 4 個指認選項必須完全等於：{self.unsure_choice_text}
- final_accuse.solution_index 必須是 0/1/2
- 開場不得出現事件詞：{", ".join(self.incident_terms)}
- 事件詞必須延後到約 40% 才第一次出現
- endings 必須明確包含『原因+道歉+教導』且至少 {self.ending_min_paragraphs} 段

# 節奏錨點（只學節奏，不得照抄）
{GOLDEN_OPENING_EXAMPLE}

# 語氣錨點（只學語氣/段落，不得照抄）
{style}

# 你要修補的上一版 JSON
{raw_text}
""".strip()

    def build_enrich_prompt(self, *, raw_json: str, theme: str, rep: Dict[str, Any]) -> str:
        style = extract_style_example()
        return f"""
你要把下面這份故事 JSON 做「最小修改」的補強（不要整個重寫），目標是：
- scene_01_start 至少 {self.opening_min_paragraphs} 段（\\n\\n 分段），且段落不重複
- ✅ 開場不得出現事件詞：{", ".join(self.incident_terms)}
- ✅ 事件詞必須在故事約 40% 之後才第一次出現（但中後段必須出現至少一次）
- 事件後至少 2～3 個 scene 做自然搜尋（問人/回到現場/對照/翻找/被打斷/再確認）
- 線索要自然：用「具體可觀察」的物件/痕跡/聲音/味道/觸感/位置
- 禁止模板線索句（例如：我們找到線索了 / 這一定是線索 / 關鍵線索）
- 禁止對讀者下指令（不要出現：{", ".join(self.gamey_patterns)}）
- ✅ endings 必須明確包含『原因+道歉+教導』且至少 {self.ending_min_paragraphs} 段

# 目前品質檢查（不要輸出）
rep={json.dumps(rep, ensure_ascii=False)}

# 本次主題
theme={theme}

# 節奏錨點（只學節奏，不得照抄）
{GOLDEN_OPENING_EXAMPLE}

# 語氣錨點（只學語氣/段落，不得照抄）
{style}

# 只輸出完整 JSON object（不要 markdown、不要解釋）

# 你要補強的 JSON
{raw_json}
""".strip()
