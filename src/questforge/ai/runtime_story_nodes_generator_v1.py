# src/questforge/ai/runtime_story_nodes_generator_v1.py
from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any, Dict, Optional
from pathlib import Path
from openai import OpenAI

from questforge.ai.story_spec_v1 import StorySpecV1
from questforge.contracts.story_nodes_v1 import (
    StoryNodesPackage,
    story_nodes_package_from_dict,
)
from questforge.contracts.story_nodes_validator_v1 import (
    StoryNodesValidationError,
    validate_story_nodes_v1,
)


def _env_bool(name: str, default: bool = False) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    v = (os.getenv(name) or "").strip()
    if not v:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _strip_code_fence(s: str) -> str:
    t = (s or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _extract_first_json(text: str) -> Any:
    s = _strip_code_fence((text or "").strip())
    if not s:
        raise RuntimeError("empty_output")

    try:
        return _loads_json_with_salvage(s)
    except Exception:
        pass

    start = s.find("{")
    if start < 0:
        raise RuntimeError("no_json_start")

    depth = 0
    for i in range(start, len(s)):
        ch = s[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return _loads_json_with_salvage(s[start : i + 1])

    raise RuntimeError("no_json_end")

def _sanitize_json_common(text: str) -> str:
    """
    嘗試修復常見「幾乎是 JSON 但壞在字串內容」的情況：
    - 字串中出現原生換行 -> 轉成 \\n
    - 字串中出現原生 tab -> 轉成 \\t
    - （不處理所有情況，但可以救回你現在這種 JSONDecodeError）
    """
    s = text

    out = []
    in_str = False
    esc = False

    for ch in s:
        if not in_str:
            if ch == '"':
                in_str = True
                out.append(ch)
            else:
                out.append(ch)
            continue

        # in_str == True
        if esc:
            out.append(ch)
            esc = False
            continue

        if ch == "\\":
            out.append(ch)
            esc = True
            continue

        if ch == '"':
            out.append(ch)
            in_str = False
            continue

        # ✅ JSON string 不能直接出現真換行/制表
        if ch == "\n":
            out.append("\\n")
            continue
        if ch == "\r":
            # 忽略或轉義皆可
            continue
        if ch == "\t":
            out.append("\\t")
            continue

        out.append(ch)

    return "".join(out)


def _loads_json_with_salvage(s: str) -> Any:
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # 再試一次：把字串裡的原生換行等控制字元轉義
        s2 = _sanitize_json_common(s)
        return json.loads(s2)


def _deep_replace_nl_escapes(obj: Any) -> Any:
    if isinstance(obj, str):
        return obj.replace("\\n", "\n")
    if isinstance(obj, list):
        return [_deep_replace_nl_escapes(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _deep_replace_nl_escapes(v) for k, v in obj.items()}
    return obj


def _autofix_package_dict(
    *,
    data: Dict[str, Any],
    theme: str,
    forced_case_id: str | None,
    spec: StorySpecV1,
) -> Dict[str, Any]:
    """
    ✅ 只做「規範修補」，不寫死故事內容
    - meta/schema/case_id
    - 必備節點保底（避免遊戲中斷）
    - 禁詞/專有名詞清洗
    - 開場主題單一化
    - ✅ 全故事去重段落（解你現在 dup_paragraphs 爆掉）
    """
    if not isinstance(data, dict):
        return data

    meta = data.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        data["meta"] = meta

    meta.setdefault("schema_version", "v1")
    spec.ensure_case_id(meta, forced_case_id)

    if not str(meta.get("title") or "").strip():
        meta["title"] = "未命名案件"
    tags = meta.get("tags")
    if not isinstance(tags, list) or not tags:
        meta["tags"] = ["ai"]

    meta["title"] = spec.remove_banned_proper_nouns(str(meta.get("title") or ""))

    nodes = data.get("nodes")
    if not isinstance(nodes, dict):
        nodes = {}
        data["nodes"] = nodes

    def _ensure_node(node_id: str, node_obj: Dict[str, Any]) -> None:
        if node_id not in nodes or not isinstance(nodes.get(node_id), dict):
            nodes[node_id] = node_obj

    # ✅ 必備節點保底（這裡只給「極短保底」，真正故事內容交給 AI）
    _ensure_node(
        "scene_01_start",
        {
            "title": "故事開始",
            "narration": "旁白：今天要開始一個熱鬧的活動。\n\n霏霏：樂樂，我們慢慢看，別衝太快。\n\n樂樂：好！我會用眼睛當雷達！",
            "choices": [{"text": "繼續聽故事", "next": "final_accuse"}],
        },
    )

    for eid in (
        "scene_10_ending_clear",
        "scene_10_ending_nudge",
        "scene_10_ending_defer",
    ):
        _ensure_node(
            eid,
            {
                "title": "結尾",
                "narration": "旁白：我們把事情說清楚了，也學到要先確認再下結論。",
                "choices": [{"text": "故事結束", "next": "quit"}],
            },
        )

    _ensure_node(
        "quit",
        {
            "title": "離開",
            "narration": "旁白：今天的故事先到這裡。我們下次再一起來看看新故事～",
            "choices": [],
            "can_replay": True,
            "can_quit": True,
        },
    )

    _ensure_node(
        "final_accuse",
        {
            "title": "最後指認",
            "narration": "旁白：你覺得比較像是哪一個人跟這件事有關？也可以交給老師一起確認。",
            "choices": [
                {"text": "東東", "next": "scene_10_ending_clear"},
                {"text": "小芽", "next": "scene_10_ending_nudge"},
                {"text": "阿力", "next": "scene_10_ending_defer"},
                {"text": "我還不確定，交給老師", "next": "scene_10_ending_defer"},
            ],
            "solution_index": 0,
        },
    )

    # ------------------------------------------------------------
    # ✅ Hard-fix: final_accuse.solution_index must be 0/1/2
    # - AI 常常會給 3 / null / "0" 之類，validator 會直接 fail
    # - 先保證能過 validate，後續 enrich 再補品質
    # ------------------------------------------------------------
    fa = nodes.get("final_accuse")
    if isinstance(fa, dict):
        si = fa.get("solution_index", 0)
        try:
            si_int = int(si)
        except Exception:
            si_int = 0

        # clamp to 0..2
        if si_int < 0:
            si_int = 0
        elif si_int > 2:
            si_int = 2

        fa["solution_index"] = si_int

        # ✅ 保險：確保 choices 結構符合 validator（4個 + 第4個固定文案）
        ch = fa.get("choices")
        if not isinstance(ch, list):
            ch = []

        # 至少 4 個
        while len(ch) < 4:
            ch.append({"text": "", "next": "scene_10_ending_defer"})

        # 只保留前 4 個
        ch = ch[:4]

        # 第 4 個 choice 必須完全一致
        c3 = ch[3] if isinstance(ch[3], dict) else {}
        c3 = dict(c3)
        c3["text"] = "我還不確定，交給老師"
        c3.setdefault("next", "scene_10_ending_defer")
        ch[3] = c3

        fa["choices"] = ch
        nodes["final_accuse"] = fa

    # ✅ 全節點文字清洗（不寫死內容，只做規範）
    for nid, node in list(nodes.items()):
        if not isinstance(node, dict):
            continue

        node["title"] = spec.remove_banned_proper_nouns(str(node.get("title") or ""))

        nar = node.get("narration")
        if isinstance(nar, str):
            nar2 = spec.remove_banned_proper_nouns(nar)
            nar2 = spec.soften_daily_tone(nar2)
            nar2 = spec.apply_competition_anti_drift(nar2, theme)

            if nid == "scene_01_start":
                nar2 = spec.replace_forbidden_opening_terms(nar2)
                nar2 = spec.normalize_opening_theme(nar2, theme)
                nar2 = spec.post_clean_opening(nar2)

            # ✅ 重要：全故事去重（解 dup_paragraphs）
            nar2 = spec.dedupe_paragraphs_global(nar2)

            node["narration"] = nar2

    # ending 強制 choices
    for eid in (
        "scene_10_ending_clear",
        "scene_10_ending_nudge",
        "scene_10_ending_defer",
    ):
        en = nodes.get(eid)
        if isinstance(en, dict):
            en["choices"] = [{"text": "故事結束", "next": "quit"}]

    # quit 強制
    qn = nodes.get("quit")
    if isinstance(qn, dict):
        qn["choices"] = []
        qn["can_replay"] = True
        qn["can_quit"] = True

    # scene_01_start choice next 必須存在
    s1 = nodes.get("scene_01_start")
    if isinstance(s1, dict):
        ch = s1.get("choices")
        if not isinstance(ch, list) or not ch or not isinstance(ch[0], dict):
            s1["choices"] = [{"text": "繼續聽故事", "next": "final_accuse"}]
        else:
            c0 = dict(ch[0])
            nxt = str(c0.get("next") or "").strip()
            if (not nxt) or (nxt not in nodes):
                c0["next"] = "final_accuse"
            if not str(c0.get("text") or "").strip():
                c0["text"] = "繼續聽故事"
            ch[0] = c0
            s1["choices"] = ch

    return data


class RuntimeStoryNodesGeneratorV1:
    """
    ✅ 規範驅動版（Spec-driven）
    - story_spec_v1.py 管規範 + prompt + gate
    - 這裡只負責流程
    """

    def __init__(self) -> None:
        self._ai_mode = (os.getenv("AI_MODE") or "mock").strip().lower()
        self._model = (os.getenv("QF_STORY_MODEL") or "gpt-4o-mini").strip()
        self._max_attempts = _env_int("QF_STORY_MAX_ATTEMPTS", 4)
        self._include_old_rival = _env_bool("QF_INCLUDE_OLD_RIVAL", False)
        self._enrich_temp = float(os.getenv("QF_STORY_ENRICH_TEMP") or "0.55")

        self._spec = StorySpecV1()

        self._client: Optional[OpenAI] = None
        if self._ai_mode == "real":
            self._client = OpenAI()

    def generate(
        self, *, seed: Optional[int] = None, forced_case_id: str | None = None
    ) -> StoryNodesPackage:
        if self._ai_mode != "real":
            return self._mock_story_nodes(seed=seed)

        assert self._client is not None

        # ✅ 把規範檔完整餵給 AI（不是只有 story_prompt_v1）
        rules_text = (
            (self._spec.prompts_dir / "story_prompt_v1.md")
            .read_text(encoding="utf-8")
            .strip()
        )

        nonce = uuid.uuid4().hex[:8]
        theme = self._spec.pick_theme(seed, nonce)

        base_prompt = self._spec.build_user_prompt(
            rules_text=rules_text,
            seed=seed,
            nonce=nonce,
            theme=theme,
            include_old_rival=self._include_old_rival,
        )

        last_err: Optional[str] = None
        raw_text: str = ""

        t0 = time.time()
        for attempt in range(1, max(1, self._max_attempts) + 1):
            if attempt == 1:
                input_text = base_prompt
                temp = 0.9
                mode = "generate"
            else:
                if (last_err or "").startswith("ENRICH_FAIL"):
                    input_text = self._spec.build_enrich_prompt(
                        raw_json=raw_text, theme=theme, rep={"error": last_err}
                    )
                    temp = self._enrich_temp
                    mode = "enrich_repair"
                else:
                    input_text = self._spec.build_repair_prompt(
                        raw_text=raw_text,
                        error=last_err or "unknown_error",
                        theme=theme,
                    )
                    temp = 0.2
                    mode = "repair"

            print(
                f"[AI_GEN] attempt={attempt} mode={mode} model={self._model}",
                flush=True,
            )

            try:
                resp = self._client.responses.create(
                    model=self._model,
                    input=input_text,
                    temperature=temp,
                    max_output_tokens=7000,
                    response_format={"type": "json_object"},
                )
            except Exception:
                resp = self._client.responses.create(
                    model=self._model,
                    input=input_text,
                    temperature=temp,
                    max_output_tokens=7000,
                )

            raw_text = (resp.output_text or "").strip()
            if not raw_text:
                last_err = "empty_output_text"
                print("[AI_GEN] empty output_text", flush=True)
                continue

            print("[AI_RAW_HEAD]", raw_text[:260].replace("\n", "\\n"), flush=True)

            try:
                data = _extract_first_json(raw_text)
                if not isinstance(data, dict):
                    last_err = "top_level_not_object"
                    continue

                data = _deep_replace_nl_escapes(data)
                data = _autofix_package_dict(
                    data=data,
                    theme=theme,
                    forced_case_id=forced_case_id,
                    spec=self._spec,
                )

                pkg = story_nodes_package_from_dict(data)
                validate_story_nodes_v1(pkg)

                nodes = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}

                # ✅ gate：不足就走 enrich（AI 來補，不是你寫死）
                if self._spec.needs_enrich(nodes=nodes):
                    rep = {
                        "opening_paragraphs": self._spec.opening_paragraphs(nodes),
                        "clue": self._spec.clue_quality_report(nodes),
                        "style": self._spec.style_quality_report(nodes),
                    }
                    last_err = f"ENRICH_FAIL rep={rep}"
                    raw_text = json.dumps(data, ensure_ascii=False, indent=2)
                    print(f"[AI_GEN] enrich_gate_fail: {rep}", flush=True)
                    continue

                # meta 保底
                if not pkg.meta.case_id.strip():
                    pkg.meta.case_id = forced_case_id or f"ai_{uuid.uuid4().hex[:10]}"
                if not pkg.meta.title.strip():
                    pkg.meta.title = "未命名案件"

                dt = time.time() - t0
                _dump_story_package_files(pkg_dict=data)
                print(
                    f"[AI_GEN] ok attempt={attempt} dt={dt:.2f}s nodes={len(pkg.nodes)} case_id={pkg.meta.case_id}",
                    flush=True,
                )
                return pkg

            except (StoryNodesValidationError, ValueError, KeyError, TypeError) as e:
                last_err = f"{type(e).__name__}: {e}"
                print("[AI_GEN] validation_fail:", last_err, flush=True)
                continue
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                print("[AI_GEN] fail:", last_err, flush=True)
                continue

        raise RuntimeError(f"story_generation_failed: {last_err}")

    def _mock_story_nodes(self, *, seed: Optional[int]) -> StoryNodesPackage:
        from questforge.content.story_case_generated_demo_v10 import STORY_NODES as DEMO_NODES  # type: ignore

        meta = {
            "schema_version": "v1",
            "case_id": f"mock_{uuid.uuid4().hex[:8]}",
            "title": "Mock：Generated Demo v10",
            "tags": ["mock"],
        }

        pkg_dict = {
            "meta": meta,
            "nodes": _engine_nodes_dict_to_story_nodes_v1(DEMO_NODES),
        }
        pkg = story_nodes_package_from_dict(pkg_dict)
        validate_story_nodes_v1(pkg)
        return pkg


def _engine_nodes_dict_to_story_nodes_v1(nodes: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for node_id, node in (nodes or {}).items():
        if not isinstance(node, dict):
            continue

        narration_text = (node.get("narration") or "").strip()
        out[node_id] = {
            "title": (node.get("title") or "").strip(),
            "narration": narration_text,
            "choices": node.get("choices") or [],
        }

        if "solution_index" in node:
            out[node_id]["solution_index"] = node.get("solution_index")
        if "can_replay" in node:
            out[node_id]["can_replay"] = node.get("can_replay")
        if "can_quit" in node:
            out[node_id]["can_quit"] = node.get("can_quit")

    return out


def _dump_story_package_files(*, pkg_dict: Dict[str, Any]) -> None:
    cache = Path(".qf_cache/generated_stories")
    cache.mkdir(parents=True, exist_ok=True)

    meta = pkg_dict.get("meta") if isinstance(pkg_dict, dict) else {}
    case_id = str((meta or {}).get("case_id") or "unknown_case").strip() or "unknown_case"
    title = str((meta or {}).get("title") or "").strip()

    # 1) 原始 JSON（漂亮縮排）
    (cache / f"{case_id}.json").write_text(
        json.dumps(pkg_dict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 2) 純文字方便快速看（把每個 node 的 narration 拉出來）
    nodes = pkg_dict.get("nodes") if isinstance(pkg_dict, dict) else {}
    lines: list[str] = []
    lines.append(f"case_id={case_id}")
    if title:
        lines.append(f"title={title}")
    lines.append("")

    if isinstance(nodes, dict):
        for nid, node in nodes.items():
            if not isinstance(node, dict):
                continue
            lines.append(f"== {nid} :: {node.get('title','')} ==")
            nar = node.get("narration")
            if isinstance(nar, str):
                lines.append(nar.strip())
            lines.append("")

    (cache / f"{case_id}.txt").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")