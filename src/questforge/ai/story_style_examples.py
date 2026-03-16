from __future__ import annotations

import hashlib
from pathlib import Path

from questforge.ai.story_prompt_assets import STYLE_EXAMPLE_CONTENT

_SAMPLES_DIR = Path(__file__).resolve().parents[3] / "samples" / "samples"

_OPENING_EVENT_FILES = [
    "003_茉莉山的度假山莊.md",
    "004_三年丙班失竊案.md",
    "005_餅乾鎮的夢幻甜點.md",
    "008_百貨公司失竊案.md",
    "013_夏日的迷途馬拉松.md",
    "016_選美大會的完美犯罪.md",
    "019_陽光號的巡航冒險.md",
    "020_雪地救援.md",
]

_HUMAN_TWIST_FILES = [
    "001_好吃到爆炸的千層麵.md",
    "002_雨衣怪客跟蹤奇案.md",
    "003_茉莉山的度假山莊.md",
    "004_三年丙班失竊案.md",
    "008_百貨公司失竊案.md",
    "013_夏日的迷途馬拉松.md",
    "016_選美大會的完美犯罪.md",
    "018_傷心的瘋狂畫家.md",
    "019_陽光號的巡航冒險.md",
]


def _excerpt_from_sample(path: Path, *, max_nonempty_lines: int) -> list[str]:
    if not path.exists():
        return []

    out: list[str] = []
    nonempty = 0
    prev_blank = True
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            if out and not prev_blank:
                out.append("")
                prev_blank = True
            continue

        if stripped.startswith("#") or stripped.startswith(">"):
            continue

        out.append(stripped)
        nonempty += 1
        prev_blank = False
        if nonempty >= max_nonempty_lines:
            break

    while out and not out[-1].strip():
        out.pop()
    return out


def _sample_style_files() -> list[str]:
    if not _SAMPLES_DIR.exists():
        return []
    return sorted(
        p.name
        for p in _SAMPLES_DIR.glob("*.md")
        if p.is_file()
    )


def _pick_sample_files(*, selector: str, count: int, focus: str = "general") -> list[str]:
    files = _sample_style_files()
    if not files:
        return []

    if focus == "opening_event":
        focused = [name for name in _OPENING_EVENT_FILES if name in files]
        if focused:
            files = focused
    elif focus == "human_twist":
        focused = [name for name in _HUMAN_TWIST_FILES if name in files]
        if focused:
            files = focused

    wanted = max(1, min(count, len(files)))
    base = selector or "default"
    keyed = []
    for name in files:
        digest = hashlib.sha1(f"{base}:{name}".encode("utf-8")).hexdigest()
        keyed.append((digest, name))
    keyed.sort()
    return [name for _, name in keyed[:wanted]]


def extract_style_example(max_lines: int = 72, *, selector: str = "", focus: str = "general") -> str:
    chosen_files = _pick_sample_files(
        selector=selector,
        count=max(3, min(5, max_lines // 18)),
        focus=focus,
    )
    per_file = max(14, max_lines // max(1, len(chosen_files)))
    chunks: list[str] = []

    for name in chosen_files:
        excerpt = _excerpt_from_sample(_SAMPLES_DIR / name, max_nonempty_lines=per_file)
        if not excerpt:
            continue
        chunks.append(f"【樣本摘錄：{name}】")
        chunks.extend(excerpt)
        chunks.append("")

    if chunks:
        while chunks and not chunks[-1].strip():
            chunks.pop()
        return "\n".join(chunks).strip()

    lines = STYLE_EXAMPLE_CONTENT.splitlines()
    return "\n".join(lines[:max_lines]).strip()
