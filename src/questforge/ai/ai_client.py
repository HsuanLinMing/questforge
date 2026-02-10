# src/questforge/ai/ai_client.py
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Protocol

from openai import OpenAI

from questforge.ai.schemas import StoryPackage
from questforge.ai.storypackage_codec import storypackage_from_dict, StoryPackageParseError

AI_MODE = (os.getenv("AI_MODE") or "mock").strip().lower()
OPENAI_MODEL = (os.getenv("QF_STORY_MODEL") or "gpt-4o-mini").strip()
PROMPT_PATH = Path("src/questforge/ai/prompts/story_prompt_v1.md")


class AiClient(Protocol):
    def generate_story(self, seed: int | None = None) -> StoryPackage: ...


class MockAiClient:
    def generate_story(self, seed: int | None = None) -> StoryPackage:
        from questforge.ai.mock_story import build_mock_story
        return build_mock_story()


class RealAiClient:
    def __init__(self) -> None:
        self._client = OpenAI()

    def _load_prompt(self) -> str:
        try:
            return PROMPT_PATH.read_text(encoding="utf-8")
        except Exception:
            return (
                "You are a story writer for a kid-friendly detective adventure game.\n"
                "Output a JSON object that matches the required keys.\n"
            )

    def _build_user_prompt(self, *, seed: int | None, nonce: str) -> str:
        rules = self._load_prompt()
        seed_line = f"{int(seed)}" if seed is not None else "null"
        return f"""
{rules}

# IMPORTANT OUTPUT FORMAT (MUST FOLLOW)
Return ONLY a JSON object (no markdown, no code fence) with EXACT keys:

{{
  "case_id": "ai_xxx",
  "title": "...",
  "prologue": "...",
  "characters": [{{"name":"...","role":"...","notes":"..."}}],
  "scenes": [
    {{
      "title": "...",
      "narration": "...",
      "observations": [{{"text":"..."}}]
    }}
  ],
  "cooldown_dialogue": "...",
  "teacher_scene": "...",
  "open_ending": "...",
  "tags": ["..."]
}}

Notes:
- No culprit / no answer / no motive labels.
- narration should use Chinese.
- Keep it kid-friendly.
- seed={seed_line}, nonce={nonce} (do NOT output seed/nonce fields)
"""

    def _repair_prompt(self, raw_text: str, error: str) -> str:
        return f"""
Your previous output did NOT match the required JSON schema.

Error:
{error}

Fix the JSON to match EXACT required keys and types.
Return ONLY the corrected JSON object (no markdown).

Previous output:
{raw_text}
"""

    def generate_story(self, seed: int | None = None) -> StoryPackage:
        nonce = uuid.uuid4().hex[:8]
        user_prompt = self._build_user_prompt(seed=seed, nonce=nonce)

        resp = self._client.responses.create(
            model=OPENAI_MODEL,
            input=user_prompt,
            temperature=0.9,
            max_output_tokens=2600,
        )
        text = (resp.output_text or "").strip()
        if not text:
            raise RuntimeError("empty_story_output")

        # 1st try
        data = _extract_first_json(text)
        if isinstance(data, dict):
            data.setdefault("case_id", f"ai_{uuid.uuid4().hex[:10]}")

        try:
            return storypackage_from_dict(data)
        except StoryPackageParseError as e:
            # 2nd try: repair once
            repair = self._repair_prompt(text, str(e))
            resp2 = self._client.responses.create(
                model=OPENAI_MODEL,
                input=repair,
                temperature=0.2,
                max_output_tokens=2600,
            )
            text2 = (resp2.output_text or "").strip()
            if not text2:
                raise

            data2 = _extract_first_json(text2)
            if isinstance(data2, dict):
                data2.setdefault("case_id", f"ai_{uuid.uuid4().hex[:10]}")

            return storypackage_from_dict(data2)


def build_ai_client() -> AiClient:
    if AI_MODE == "real":
        return RealAiClient()
    return MockAiClient()


def _extract_first_json(text: str) -> Any:
    s = text.strip()
    try:
        return json.loads(s)
    except Exception:
        pass

    start = s.find("{")
    if start < 0:
        raise RuntimeError("no_json_object_start")
    depth = 0
    for i in range(start, len(s)):
        ch = s[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[start : i + 1])
    raise RuntimeError("no_json_object_end")
