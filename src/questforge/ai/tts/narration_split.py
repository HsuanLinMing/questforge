# src/questforge/ai/tts/narration_split.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class NarrationLine:
    """A parsed narration line.

    `raw` is the original paragraph (trimmed).
    `role` defaults to "旁白" when not specified.
    """

    index: int
    role: str
    text: str
    raw: str


def parse_role_text(paragraph: str, *, default_role: str = "旁白") -> tuple[str, str]:
    """Parse '角色：內容'. If delimiter missing, treat as narration."""

    p = (paragraph or "").strip()
    if not p:
        return default_role, ""

    if "：" in p:
        role, text = p.split("：", 1)
        role = (role or "").strip() or default_role
        text = (text or "").strip()
        return role, text

    if ":" in p:  # halfwidth fallback
        role, text = p.split(":", 1)
        role = (role or "").strip() or default_role
        text = (text or "").strip()
        return role, text

    return default_role, p


def split_narration(narration: str | None) -> List[NarrationLine]:
    """Split narration into role-annotated lines.

    Convention:
    - paragraphs separated by blank line ("\n\n")
    - paragraph may start with '角色：'

    Returns stable indices for UI highlighting.
    """

    blocks: Iterable[str] = (narration or "").split("\n\n")

    out: List[NarrationLine] = []
    i = 0
    for b in blocks:
        raw = (b or "").strip()
        if not raw:
            continue
        role, text = parse_role_text(raw)
        if not (text or "").strip():
            continue
        out.append(NarrationLine(index=i, role=role, text=text, raw=raw))
        i += 1

    return out
