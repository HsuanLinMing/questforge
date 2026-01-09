from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any, Literal

ReasonInputMode = Literal["choice", "text", "voice"]


@dataclass
class DetectiveState:
    """偵探向遊戲狀態（純故事 / 推理用）。

    這是「核心領域模型（core）」：
    - 不依賴 CLI/Flutter
    - 可被存成 JSON
    - 供推理計分、分支判斷、回顧顯示使用
    """

    turn: int = 0
    clues: Set[str] = field(default_factory=set)
    clue_labels: Dict[str, str] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    flags: Set[str] = field(default_factory=set)
    vars: Dict[str, int] = field(default_factory=dict)
    last_accuse: str = ""  # 玩家最後一次指認的 suspect_id（或 ""）
    last_reason_id: str = ""  # Day8 先不用也行，先留著
    last_reason_text: str = ""  # 預留語音/自由文字（B）
    last_reason_ids: List[str] = field(default_factory=list)

    def add_clue(self, clue: str) -> bool:
        """新增線索 key（Set 去重）。回傳 True 表示第一次收集到。"""
        clue = clue.strip()
        if not clue:
            return False
        before = len(self.clues)
        self.clues.add(clue)
        return len(self.clues) > before

    def add_clue_with_label(self, key: str, label: str | None = None) -> bool:
        """新增線索（key）並記下中文說明（label）。回傳 True 表示第一次收集到。"""
        key = (key or "").strip()
        if not key:
            return False

        is_new = self.add_clue(key)

        if label:
            label = str(label).strip()
            if label:
                self.clue_labels[key] = label

        if is_new and self.clue_labels.get(key):
            self.add_note(f"【線索】{self.clue_labels[key]}")

        return is_new

    def add_note(self, note: str) -> None:
        """新增偵探筆記（保留順序）。"""
        note = note.strip()
        if note:
            self.notes.append(note)

    def set_flag(self, flag: str) -> bool:
        """設定旗標（Set 去重）。回傳 True 表示第一次設定到。"""
        flag = flag.strip()
        if not flag:
            return False
        before = len(self.flags)
        self.flags.add(flag)
        return len(self.flags) > before

    def inc(self, key: str, delta: int = 1) -> int:
        """遞增變數（適合做計數，例如問了幾次）。回傳新值。"""
        key = key.strip()
        if not key:
            return 0
        self.vars[key] = int(self.vars.get(key, 0)) + int(delta)
        return self.vars[key]

    def to_dict(self) -> Dict[str, Any]:
        """存檔：把狀態轉成可 JSON 序列化的 dict。"""
        return {
            "turn": self.turn,
            "clues": sorted(self.clues),
            "clue_labels": dict(self.clue_labels),
            "notes": list(self.notes),
            "flags": sorted(self.flags),
            "vars": dict(self.vars),
            "last_accuse": self.last_accuse,
            "last_reason_id": self.last_reason_id,
            "last_reason_text": self.last_reason_text,
            "last_reason_ids": list(self.last_reason_ids),  # ✅ Day9
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DetectiveState":
        """讀檔：從 dict 還原狀態。"""
        state = cls()
        state.turn = int(data.get("turn", 0))
        state.clues = set(data.get("clues", []))
        state.clue_labels = dict(data.get("clue_labels", {}))
        state.notes = list(data.get("notes", []))
        state.flags = set(data.get("flags", []))
        state.vars = {str(k): int(v) for k, v in dict(data.get("vars", {})).items()}
        state.last_accuse = str(data.get("last_accuse", ""))
        state.last_reason_id = str(data.get("last_reason_id", ""))
        state.last_reason_text = str(data.get("last_reason_text", ""))
        state.last_reason_ids = list(data.get("last_reason_ids", []))
        if not state.last_reason_ids and state.last_reason_id:
            state.last_reason_ids = [state.last_reason_id]
        return state


@dataclass
class GameConfig:
    """遊戲設定（可由 CLI/Flutter/FastAPI 注入）。

    - enable_quiz：是否開啟「回顧問答」
    - quiz_can_skip：回顧問答是否允許跳過
    """

    enable_quiz: bool = False
    quiz_can_skip: bool = True
    reason_input_mode: ReasonInputMode = "choice"


@dataclass
class AccuseReasonOption:
    """指認理由（A 模式的選項）。
    - reason_id：穩定 key，後續語音 mapping 也會 map 成它
    - text：給玩家看的理由文字
    - expected_evidence：這個理由「通常對應到」哪些線索（用於加權）
    - base_score：即使沒線索也給一點分（避免孩子全空）
    """

    reason_id: str
    text: str
    expected_evidence: List[str] = field(default_factory=list)
    base_score: int = 0


@dataclass
class AccuseConfig:
    """案件的指認設定（每個 case 一份）。
    - suspects：可指認的對象 id（或名字）
    - reasons：理由選項（A）
    - truth：正解（可選，用於結局/回饋；但不必當作卡關）
    - key_evidence：關鍵證據權重（線索 -> 分數）
    - min_good_score：達到這個分數就算推理很成熟
    """

    suspects: List[str]
    reasons: List[AccuseReasonOption]
    truth: Optional[str] = None

    key_evidence: Dict[str, int] = field(default_factory=dict)
    min_good_score: int = 6


@dataclass
class AccuseResult:
    """玩家一次指認的輸入資料（Day9：多理由）。
    - target：指認對象
    - reason_ids：多理由（A）
    - reason_id：舊欄位相容（Day8）
    - reason_text：預留 B
    """

    target: str
    reason_ids: List[str] = field(default_factory=list)

    # backward compatible
    reason_id: str = ""
    reason_text: str = ""

    def normalized_reason_ids(self) -> List[str]:
        ids = [str(x).strip() for x in (self.reason_ids or []) if str(x).strip()]
        if not ids and self.reason_id.strip():
            ids = [self.reason_id.strip()]
        # 去重但保序
        seen = set()
        out: List[str] = []
        for x in ids:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out



@dataclass
class ReasoningFeedback:
    """推理回饋（不是對錯判定，是成熟度/建議）。"""

    score: int
    level: Literal["weak", "ok", "good"]
    matched_evidence: List[str] = field(default_factory=list)
    missing_key_evidence: List[str] = field(default_factory=list)
    message: str = ""
