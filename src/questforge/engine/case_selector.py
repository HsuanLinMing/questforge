import random
from typing import Dict, Set

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

    def pick(self) -> dict:
        available = [
            key for key in self._cases.keys()
            if key not in self._played
        ]

        # 如果全部都玩過，就重置
        if not available:
            self._played.clear()
            available = list(self._cases.keys())

        key = random.choice(available)
        self._played.add(key)
        return self._cases[key]
