from __future__ import annotations

"""CASES 自動驗證（啟動時可選）。

使用方式：
- 在 src/questforge/content/cases.py 末尾呼叫：

    from questforge.content.validator import validate_cases_if_enabled
    validate_cases_if_enabled(CASES)

- 預設不會阻擋啟動（只在 env var 開啟時才會 raise）

環境變數：
- QUESTFORGE_VALIDATE_CASES=1     -> 有 error 就 raise ValueError
- QUESTFORGE_VALIDATE_CASES=true  -> 同上
- QUESTFORGE_VALIDATE_CASES=warn  -> 只印出 error/warning，不 raise

（你可以在本機開發 / CI 依情境開關）
"""

import os
from typing import Any, Dict

from questforge.content.story_lint import lint_cases


def _env_mode() -> str:
    v = (os.environ.get("QUESTFORGE_VALIDATE_CASES") or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return "raise"
    if v in ("warn", "warning", "print"):
        return "warn"
    return "off"


def validate_cases_if_enabled(cases: Dict[str, Any]) -> None:
    mode = _env_mode()
    if mode == "off":
        return

    rpt = lint_cases(cases)
    txt = rpt.to_text()
    if txt:
        print("\n[QuestForge] CASES lint report")
        print(txt)
        print("")

    if mode == "raise" and not rpt.ok:
        raise ValueError("QuestForge CASES validation failed. See lint report above.")
