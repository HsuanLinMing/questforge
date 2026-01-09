from __future__ import annotations

from dataclasses import dataclass
from typing import List


MENTAL_STATE_TERMS = [
    # 情緒/心理
    "緊張",
    "不安",
    "害怕",
    "心虛",
    "焦慮",
    "擔心",
    "著急",
    "生氣",
    "難過",
    "委屈",
    "嫉妒",
    "羨慕",
    "愧疚",
    # 動機/意圖（容易變成定罪）
    "想偷",
    "偷了",
    "故意",
    "蓄意",
    "別有用心",
    "想陷害",
    "想害",
    "想要",
    "就是要",
    "一定是",
    "肯定是",
]

# 也可以加一些「心理句型」(很常見)
MENTAL_PATTERNS = [
    "看起來很",
    "好像很",
    "似乎",
    "感覺他",
    "感覺她",
    "我覺得他",
    "我覺得她",
]

# 你可依你的「黑名單」慢慢擴充
BLACKLIST_TERMS = [
    "一定是",
    "就是他",
    "真兇",
    "犯人",
    "兇手",
    "最可能",
    "肯定",
    "八成",
]

# 軟警告：不一定違規，但容易變成引導/評價
SOFT_WARN_TERMS = [
    "你應該",
    "你一定",
    "你怎麼會",
    "你很聰明所以",
]


@dataclass
class GuardResult:
    ok: bool
    errors: List[str]
    warnings: List[str]
    # ✅ 新增：修正後的安全文字（沒有修正就等於原文）
    sanitized: str = ""


def _contains_mental_inference(text: str) -> bool:
    t = text or ""
    if any(w in t for w in MENTAL_STATE_TERMS):
        return True
    # 句型命中 + 某些詞同時出現（避免過度誤判）
    if any(p in t for p in MENTAL_PATTERNS) and any(
        w in t for w in ["緊張", "不安", "害怕", "心虛", "焦慮", "擔心"]
    ):
        return True
    return False


def _sanitize_mental_inference(text: str) -> str:
    """
    盡量保留原本的觀察句，把心理推測句砍掉/改寫成觀察+安全下一步。
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    kept: list[str] = []

    for ln in lines:
        if _contains_mental_inference(ln):
            continue
        kept.append(ln)

    # 如果全部被砍光，給保底
    if not kept:
        kept = [
            "我們先把看到的觀察收好。",
            "現在不急著下結論。",
            "接下來找老師一起確認。",
        ]
    else:
        # 尾句補一個安全下一步（如果沒有）
        joined = " ".join(kept)
        if ("找老師" not in joined) and ("先停一下" not in joined):
            kept.append("接下來找老師一起確認。")

    # 仍維持 2~4 句
    kept = kept[:4]
    while len(kept) < 2:
        kept.append("我們慢慢來就好。")

    return "\n".join(kept).strip()


def guard_response(text: str) -> GuardResult:
    """文案白名單檢查 + 必要時做安全修正（sanitized）。"""
    t = (text or "").strip()
    errors: List[str] = []
    warnings: List[str] = []

    sanitized = t  # ✅ 預設不改

    # 用「換行」當句子切分（你目前文案都是 \n）
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    q_count = t.count("?") + t.count("？")

    # --- Hard rules ---
    # 1) 2~4 句
    if not (2 <= len(lines) <= 4):
        errors.append(f"句數不在 2~4 句（目前 {len(lines)} 句）")

    # 2) 最多 1 個問句
    if q_count > 1:
        errors.append(f"問句過多（{q_count} 個）")

    # 3) 禁止詞
    for bad in BLACKLIST_TERMS:
        if bad in t:
            errors.append(f"出現禁止詞：{bad}")

    # --- Soft warnings ---
    for soft in SOFT_WARN_TERMS:
        if soft in t:
            warnings.append(f"可能帶有引導/評價語氣：{soft}")

    # ✅ 新增：心理/動機推測 -> warning + 自動修正
    if _contains_mental_inference(t):
        warnings.append("偵測到心理/動機推測用語，已自動改成純觀察說法。")
        sanitized = _sanitize_mental_inference(t)

    return GuardResult(
        ok=(len(errors) == 0),
        errors=errors,
        warnings=warnings,
        sanitized=sanitized,
    )
