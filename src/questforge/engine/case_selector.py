import random
from typing import Any, Dict, Set, Tuple


class CaseSelector:
    """
    案件選擇器
    - 預設隨機
    - 會避免重複，直到所有案件都玩過

    Flutter 類比：
    - 像一個 Controller，管理「下一個頁面要去哪」
    """

    def __init__(self, cases: Dict[str, dict]):
        self._cases = cases
        self._played: Set[str] = set()

    def pick(self) -> Tuple[str, dict]:
        available = [k for k in self._cases.keys() if k not in self._played]

        if not available:
            self._played.clear()
            available = list(self._cases.keys())

        key = random.choice(available)
        self._played.add(key)
        return key, self._cases[key]
