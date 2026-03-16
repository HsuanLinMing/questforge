from __future__ import annotations

import os

from openai import OpenAI

from questforge.ai.ai_client import AiClient
from questforge.ai.openai_env import get_clean_openai_api_key
from questforge.ai.response_guard import guard_response
from questforge.ai.schemas import ResponsePackage, ResponseRequest, StoryPackage
from questforge.ai.prompt_builder import SYSTEM_RULES, build_user_prompt


def _clamp_lines(
    text: str, *, min_lines: int = 2, max_lines: int = 4, max_q: int = 1
) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) < min_lines:
        while len(lines) < min_lines:
            lines.append("我們慢慢來就好。")
    if len(lines) > max_lines:
        lines = lines[:max_lines]

    q = 0
    out = []
    for ln in lines:
        q += ln.count("？") + ln.count("?")
        out.append(ln)
        if q > max_q:
            break

    return "\n".join(out).strip()


class RealAiClient(AiClient):
    """Real AI client (OpenAI).

    - Day15: ONLY response generation (intent whitelist).
    - Story generation stays disabled for now.
    """

    def __init__(self) -> None:
        # SDK 會自動讀 OPENAI_API_KEY，但我們也明確傳入以便 debug
        self._client = OpenAI(api_key=get_clean_openai_api_key())
        self._model = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()

    def generate_story(self) -> StoryPackage:
        raise NotImplementedError("RealAiClient.generate_story is not wired yet.")

    def generate_response(self, req: ResponseRequest) -> ResponsePackage:
        raw = self._call_openai(req)
        raw = _clamp_lines(raw)

        gr = guard_response(raw)
        text = self._guard_result_text(gr, fallback=raw).strip()

        return ResponsePackage(intent=req.intent, role=req.role, text=text)

    def _call_openai(self, req: ResponseRequest) -> str:
        prompt = build_user_prompt(req)

        resp = self._client.responses.create(
            model=self._model,
            instructions=SYSTEM_RULES,
            input=prompt,
            store=False,
        )

        return (resp.output_text or "").strip()

    # --------------------------
    # GuardResult compatibility
    # --------------------------
    def _guard_result_text(self, gr: object, fallback: str) -> str:
        for attr in (
            "sanitized",
            "output",
            "result",
            "final",
            "fixed",
            "safe_text",
            "message",
            "value",
            "content",
            "text",
        ):
            v = getattr(gr, attr, None)
            if isinstance(v, str) and v.strip():
                return v
        return fallback
