from dataclasses import dataclass, field
from typing import Dict, List, Set


@dataclass
class DetectiveState:
    """偵探向遊戲狀態（純故事 / 推理用）。

    - turn：回合數（用來顯示進度、或做節奏控制）
    - clues：已收集線索 key（Set 避免重複，給推理計分用）
    - clue_labels：線索 key -> 中文說明（給 UI/回顧顯示用）
    - notes：偵探筆記（List 保留順序，適合回顧）
    - flags：劇情旗標（Set，用於分支條件：例如 'saw_camera', 'met_teacher'）
    - vars：可選的變數倉庫（Dict，存一些計數/狀態，例如 {'asked_guard': 2}）
    """

    turn: int = 0
    clues: Set[str] = field(default_factory=set)
    clue_labels: Dict[str, str] = field(default_factory=dict)  # ✅ 新增
    notes: List[str] = field(default_factory=list)
    flags: Set[str] = field(default_factory=set)
    vars: Dict[str, int] = field(default_factory=dict)

    # --- helpers ---
    def add_clue(self, clue: str) -> bool:
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

        # label 只要有，就記住（即使不是新線索，也允許補上 label）
        if label:
            label = str(label).strip()
            if label:
                self.clue_labels[key] = label

        # 可選：第一次拿到線索，就寫入筆記（方便回顧）
        if is_new and self.clue_labels.get(key):
            self.add_note(f"【線索】{self.clue_labels[key]}")

        return is_new

    def add_note(self, note: str) -> None:
        note = note.strip()
        if note:
            self.notes.append(note)

    def set_flag(self, flag: str) -> bool:
        flag = flag.strip()
        if not flag:
            return False
        before = len(self.flags)
        self.flags.add(flag)
        return len(self.flags) > before

    def inc(self, key: str, delta: int = 1) -> int:
        key = key.strip()
        if not key:
            return 0
        self.vars[key] = int(self.vars.get(key, 0)) + int(delta)
        return self.vars[key]


@dataclass
class CaseConfig:
    case_id: str
    difficulty: str  # "short" | "medium" | "long"
    min_required_clues: int = 2


@dataclass
class GameConfig:
    enable_quiz: bool = False  # 是否開啟「偵探回顧問答」
    quiz_can_skip: bool = True  # 問答可跳過（更像遊戲）


@dataclass
class Progress:
    short_play_count: int = 0
    solved_count: int = 0  # 成功破案次數（跨所有難度）
    # 可選：統計各難度破案
    short_solved: int = 0
    medium_solved: int = 0
    long_solved: int = 0

    def unlocked(self) -> set[str]:
        unlocked = {"short"}
        if self.short_play_count >= 3:
            unlocked.add("medium")
        if self.solved_count >= 5:
            unlocked.add("long")
        return unlocked
