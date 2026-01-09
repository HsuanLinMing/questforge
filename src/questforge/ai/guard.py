from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict
import re


# ==============================
# Result
# ==============================

@dataclass
class GuardResult:
    ok: bool
    errors: List[str]
    warnings: List[str]
    stats: Dict[str, int]


# ==============================
# Rules (Day13-E)
# ==============================

# ❌ 絕對禁止（出現即 error）
FORBIDDEN_KEYWORDS = [
    # 裁決 / 定罪
    "真兇",
    "犯人",
    "就是他",
    "一定是",
    "百分之百",
    "最可疑",
    "兇手",
    # 對錯評價
    "答對",
    "答錯",
    "選對",
    "選錯",
    "正確答案",
    # 羞辱 / 貶低
    "笨",
    "沒用",
    "怎麼連",
    "你怎麼會",
]

# ⚠️ 不建議（但不阻斷）
SOFT_BAD_KEYWORDS = [
    "請稍後",
    "系統",
    "客服",
    "請重新操作",
]

# 句子 / 問句限制
MIN_SENTENCES = 2
MAX_SENTENCES = 4
MAX_QUESTIONS = 1

ROLE_PREFIXES = ("霏霏：", "樂樂：", "老師：")


# ==============================
# Helpers
# ==============================

def _count_sentences(text: str) -> int:
    # 你的系統已經用「換行」當主要分句方式
    return len([ln for ln in text.splitlines() if ln.strip()])


def _count_questions(text: str) -> int:
    return text.count("？") + text.count("?")


def _has_role_prefix(text: str) -> bool:
    return any(text.strip().startswith(p) for p in ROLE_PREFIXES)


def _has_double_prefix(text: str) -> bool:
    for p in ROLE_PREFIXES:
        if text.strip().startswith(p + p):
            return True
    return False


# ==============================
# Main Guard
# ==============================

def guard_response(text: str) -> GuardResult:
    """
    Day13-E Guard
    - 只檢查、不阻斷
    - errors：不可出現（❌）
    - warnings：建議修正（⚠️）
    """

    errors: List[str] = []
    warnings: List[str] = []

    clean = (text or "").strip()

    # --- stats ---
    sentence_count = _count_sentences(clean)
    question_count = _count_questions(clean)

    stats = {
        "sentences": sentence_count,
        "questions": question_count,
    }

    # ==========================
    # Sentence count
    # ==========================
    if sentence_count < MIN_SENTENCES:
        warnings.append(
            f"句子過短（{sentence_count} 句），可能太像客服或提示語"
        )

    if sentence_count > MAX_SENTENCES:
        warnings.append(
            f"句子過長（{sentence_count} 句），可能變成說教"
        )

    # ==========================
    # Question count
    # ==========================
    if question_count > MAX_QUESTIONS:
        warnings.append(
            f"問句過多（{question_count} 個），容易讓孩子有被逼問感"
        )

    # ==========================
    # Forbidden keywords
    # ==========================
    for kw in FORBIDDEN_KEYWORDS:
        if kw in clean:
            errors.append(f"出現禁止用語：『{kw}』")

    # ==========================
    # Soft bad keywords
    # ==========================
    for kw in SOFT_BAD_KEYWORDS:
        if kw in clean:
            warnings.append(f"出現偏客服語氣：『{kw}』")

    # ==========================
    # Role prefix
    # ==========================
    if not _has_role_prefix(clean):
        warnings.append("未使用角色前綴（霏霏／樂樂／老師）")

    if _has_double_prefix(clean):
        warnings.append("角色前綴重複（可能被加了兩次）")

    # ==========================
    # Result
    # ==========================
    ok = len(errors) == 0

    return GuardResult(
        ok=ok,
        errors=errors,
        warnings=warnings,
        stats=stats,
    )
