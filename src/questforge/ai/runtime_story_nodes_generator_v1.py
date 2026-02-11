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


def _sanitize_json_common(text: str) -> str:
    """
    嘗試修復常見「幾乎是 JSON 但壞在字串內容」的情況：
    - 字串中出現原生換行 -> 轉成 \\n
    - 字串中出現原生 tab -> 轉成 \\t
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
        s2 = _sanitize_json_common(s)
        return json.loads(s2)


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
    ✅ 最小 autofix（不改寫故事內容）
    只做：
    - meta/schema/case_id/tags/title 的保底
    - final_accuse：確保 choices 第4個固定文案、solution_index 合法（0/1/2）
    - endings / quit：只補「choices / can_replay / can_quit」這種結構欄位（不碰 narration）
    其他一律不動（不 replace、不 dedupe、不塞模板故事）
    """
    if not isinstance(data, dict):
        return data

    # --- meta ---
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

    # --- nodes ---
    nodes = data.get("nodes")
    if not isinstance(nodes, dict):
        # 這種情況交給 validator / repair prompt，不硬塞模板故事
        return data

    # 1) final_accuse：只做結構保險，不寫死嫌疑人名字
    fa = nodes.get("final_accuse")
    if isinstance(fa, dict):
        # clamp solution_index to 0..2
        si = fa.get("solution_index", 0)
        try:
            si_int = int(si)
        except Exception:
            si_int = 0
        if si_int < 0:
            si_int = 0
        elif si_int > 2:
            si_int = 2
        fa["solution_index"] = si_int

        # ensure choices length=4 and 4th text fixed
        ch = fa.get("choices")
        if not isinstance(ch, list):
            ch = []
        # 只補結構空位，避免崩；內容交給 repair prompt 修
        while len(ch) < 4:
            ch.append({"text": "", "next": "scene_10_ending_defer"})
        ch = ch[:4]

        c3 = ch[3] if isinstance(ch[3], dict) else {}
        c3 = dict(c3)
        c3["text"] = spec.unsure_choice_text  # ✅ 用 spec 內固定文字
        c3.setdefault("next", "scene_10_ending_defer")
        ch[3] = c3

        fa["choices"] = ch
        nodes["final_accuse"] = fa

    # 2) endings：只強制 choices 結構（不碰 narration）
    for eid in (
        "scene_10_ending_clear",
        "scene_10_ending_nudge",
        "scene_10_ending_defer",
    ):
        en = nodes.get(eid)
        if isinstance(en, dict):
            en["choices"] = [{"text": "故事結束", "next": "quit"}]

    # 3) quit：只強制 can_replay/can_quit（不碰 narration）
    qn = nodes.get("quit")
    if isinstance(qn, dict):
        qn["choices"] = []
        qn["can_replay"] = True
        qn["can_quit"] = True

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
        last_prompt: str = ""
        last_mode: str = ""
        last_attempt: int = 0
        case_id_hint = (forced_case_id or "").strip() or f"ai_{uuid.uuid4().hex[:10]}"

        t0 = time.time()
        for attempt in range(1, max(1, self._max_attempts) + 1):
            if attempt == 1:
                input_text = base_prompt
                temp = 0.9
                mode = "generate"
            else:
                if (last_err or "").startswith("ENRICH_FAIL"):
                    rep_obj = {"error": last_err}

                    # ✅ 解析 ENRICH_FAIL 後面的 JSON
                    try:
                        prefix = "ENRICH_FAIL "
                        if last_err.startswith(prefix):
                            rep_obj = json.loads(last_err[len(prefix):])
                    except Exception:
                        # keep fallback rep_obj={"error": last_err}
                        pass

                    input_text = self._spec.build_enrich_prompt(
                        raw_json=raw_text,
                        theme=theme,
                        rep=rep_obj,   # ✅ 這裡會包含 reasons / opening_paragraphs / clue / style
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

            last_prompt = input_text
            last_mode = mode
            last_attempt = attempt

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
                    text={"format": {"type": "json_object"}},
                )
                used_json_object = True
            except Exception as e:
                used_json_object = False
                print(f"[AI_GEN] response_format(json_object) unsupported -> fallback: {e!r}", flush=True)
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
                _dump_failed_ai_story_files(
                    case_id_hint=case_id_hint,
                    model=self._model,
                    mode=last_mode,
                    attempt=attempt,
                    last_err=last_err,
                    theme=theme,
                    prompt=last_prompt,
                    raw_text=raw_text,
                )
                continue

            print("[AI_RAW_HEAD]", raw_text[:260].replace("\n", "\\n"), flush=True)
            print(f"[AI_GEN] used_json_object={used_json_object}", flush=True)
            try:
                data = _extract_first_json(raw_text)

                if not isinstance(data, dict):
                    last_err = "top_level_not_object"
                    _dump_failed_ai_story_files(
                        case_id_hint=case_id_hint,
                        model=self._model,
                        mode=last_mode,
                        attempt=attempt,
                        last_err=last_err,
                        theme=theme,
                        prompt=last_prompt,
                        raw_text=raw_text,
                    )
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

                if self._spec.needs_enrich(nodes=nodes):
                    rep = self._spec.enrich_report(nodes=nodes, theme=theme)
                    last_err = "ENRICH_FAIL " + json.dumps(rep, ensure_ascii=False)
                    raw_text = json.dumps(data, ensure_ascii=False, indent=2)
                    print(f"[AI_GEN] enrich_gate_fail: {rep}", flush=True)
                    continue

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

            except json.JSONDecodeError as e:
                # ✅ 這就是你遇到的：Expecting ',' delimiter ...
                pos = int(getattr(e, "pos", 0) or 0)
                a = max(0, pos - 220)
                b = min(len(raw_text), pos + 220)
                near = raw_text[a:b].replace("\n", "\\n")

                last_err = f"JSONDecodeError: {e} (pos={pos})"
                print(f"[AI_GEN] json_decode_fail: {last_err}", flush=True)
                print(f"[AI_GEN] json_decode_near: ...{near}...", flush=True)

                _dump_failed_ai_story_files(
                    case_id_hint=case_id_hint,
                    model=self._model,
                    mode=last_mode,
                    attempt=attempt,
                    last_err=last_err,
                    theme=theme,
                    prompt=last_prompt,
                    raw_text=raw_text,
                )
                continue

            except (StoryNodesValidationError, ValueError, KeyError, TypeError) as e:
                last_err = f"{type(e).__name__}: {e}"
                print("[AI_GEN] validation_fail:", last_err, flush=True)
                _dump_failed_ai_story_files(
                    case_id_hint=case_id_hint,
                    model=self._model,
                    mode=last_mode,
                    attempt=attempt,
                    last_err=last_err,
                    theme=theme,
                    prompt=last_prompt,
                    raw_text=raw_text,
                )
                continue

            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                print("[AI_GEN] fail:", last_err, flush=True)
                _dump_failed_ai_story_files(
                    case_id_hint=case_id_hint,
                    model=self._model,
                    mode=last_mode,
                    attempt=attempt,
                    last_err=last_err,
                    theme=theme,
                    prompt=last_prompt,
                    raw_text=raw_text,
                )
                continue

        _dump_failed_ai_story_files(
            case_id_hint=case_id_hint,
            model=self._model,
            mode=last_mode,
            attempt=last_attempt,
            last_err=last_err or "unknown_error",
            theme=theme,
            prompt=last_prompt,
            raw_text=raw_text,
        )
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

    (cache / f"{case_id}.json").write_text(
        json.dumps(pkg_dict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

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


def _dump_failed_ai_story_files(
    *,
    case_id_hint: str,
    model: str,
    mode: str,
    attempt: int,
    last_err: str,
    theme: str,
    prompt: str,
    raw_text: str,
) -> None:
    """Dump prompt + raw model output for debugging, even when validation fails."""
    try:
        cache = Path(".qf_cache/generated_stories")
        cache.mkdir(parents=True, exist_ok=True)

        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        cid = (case_id_hint or "unknown").strip() or "unknown"
        safe_id = re.sub(r"[^a-zA-Z0-9_\-]+", "_", cid)[:80]
        prefix = f"FAILED_{safe_id}_A{int(attempt or 0)}"

        meta = {
            "ts": ts,
            "case_id_hint": cid,
            "model": model,
            "mode": mode,
            "attempt": int(attempt or 0),
            "last_err": last_err or "",
            "theme": theme or "",
        }
        (cache / f"{prefix}_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        (cache / f"{prefix}_prompt.txt").write_text((prompt or "").strip() + "\n", encoding="utf-8")
        (cache / f"{prefix}_raw.txt").write_text((raw_text or "").strip() + "\n", encoding="utf-8")

        preview_lines: list[str] = []
        preview_lines.append(f"ts: {ts}")
        preview_lines.append(f"case_id_hint: {cid}")
        preview_lines.append(f"model: {model}")
        preview_lines.append(f"mode: {mode}")
        preview_lines.append(f"attempt: {attempt}")
        preview_lines.append(f"theme: {theme}")
        preview_lines.append(f"last_err: {last_err}")
        preview_lines.append("")

        try:
            data = _extract_first_json(raw_text or "")
            if isinstance(data, dict):
                nodes = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
                if isinstance(nodes, dict) and nodes:
                    preview_lines.append("---- narration preview ----")
                    for nid, node in nodes.items():
                        if not isinstance(node, dict):
                            continue
                        preview_lines.append(f"== {nid} :: {node.get('title','')} ==")
                        nar = node.get("narration")
                        if isinstance(nar, str) and nar.strip():
                            preview_lines.append(nar.strip())
                        preview_lines.append("")
        except Exception:
            pass

        (cache / f"{prefix}_preview.txt").write_text(
            "\n".join(preview_lines).rstrip() + "\n",
            encoding="utf-8",
        )
        print(f"[AI_FAIL_STORY_DUMP] saved: {cache / f'{prefix}_preview.txt'}", flush=True)
    except Exception as e:
        print(f"[AI_FAIL_STORY_DUMP] fail: {e!r}", flush=True)
