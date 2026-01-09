from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

from questforge.core.models import GameConfig
from questforge.engine.session import GameSession, restore_session_from_snapshot
from questforge.engine.save_io import (
    DEFAULT_SAVE_PATH,
    load_json,
    save_json,
    slot_path,
    list_saves,
    attach_saved_at,
    snapshot_attach_case_and_config,
    read_case_id,
    read_config,
    normalize_snapshot,
)


@dataclass
class SaveMeta:
    file: str
    broken: bool = False
    case_id: str = ""
    case_title: str = ""
    turn: int = 0
    saved_at: str = ""
    enable_quiz: bool = False


class SaveManager:
    """
    SaveManager：統一管理 autosave/slot 的存檔、讀檔、列表，包含 CLI 互動 prompt。

    ✅ 保證：
    - 所有寫入的存檔，都會附上 case/config/saved_at
    - 讀檔一定 normalize + 用存檔內 case_id/config 重建 session
    """

    def __init__(self, cases: Dict[str, dict], *, saves_dir: str = "saves") -> None:
        self._cases = cases
        self._saves_dir = saves_dir

    # ----------------------------
    # Paths
    # ----------------------------
    def autosave_path(self) -> str:
        return DEFAULT_SAVE_PATH

    def slot_path(self, slot: int) -> str:
        return slot_path(slot)

    # ----------------------------
    # List
    # ----------------------------
    def list(self) -> List[SaveMeta]:
        raw = list_saves(self._saves_dir)
        out: List[SaveMeta] = []
        for m in raw:
            if m.get("broken"):
                out.append(SaveMeta(file=m["file"], broken=True))
                continue
            out.append(
                SaveMeta(
                    file=m.get("file", ""),
                    broken=False,
                    case_id=m.get("case_id", "") or "",
                    case_title=m.get("case_title", "") or "",
                    turn=int(m.get("turn", 0) or 0),
                    saved_at=m.get("saved_at", "") or "",
                    enable_quiz=bool(m.get("enable_quiz", False)),
                )
            )
        return out

    def print_list(self) -> None:
        saves = self.list()
        print("\n" + "=" * 40)
        print("【存檔列表】")
        if not saves:
            print("（目前沒有任何存檔）")
        else:
            for i, m in enumerate(saves, start=1):
                if m.broken:
                    print(f"{i}. {m.file}  [壞檔/無法解析]")
                    continue
                title = m.case_title or "（未知案件）"
                saved_at = m.saved_at or "-"
                quiz = "ON" if m.enable_quiz else "OFF"
                print(f"{i}. {m.file} | {title} | 回合 {m.turn} | quiz {quiz} | {saved_at}")
        print("=" * 40)

    # ----------------------------
    # CLI prompts
    # ----------------------------
    def prompt_save_target_path(self) -> str:
        """CLI：詢問要存到 autosave 或 slot_1/2/3，回傳實際 file path。"""
        print("\n要存到哪一格？")
        print("  A. autosave.json（快速存檔）")
        print("  1. slot_1.json")
        print("  2. slot_2.json")
        print("  3. slot_3.json")
        raw = input("請輸入 A 或 1/2/3（預設 1）：").strip().lower()

        if raw in ("", "1"):
            return self.slot_path(1)
        if raw == "2":
            return self.slot_path(2)
        if raw == "3":
            return self.slot_path(3)
        if raw == "a":
            return self.autosave_path()

        print("輸入不正確，改存 slot_1。")
        return self.slot_path(1)

    def prompt_load_source_path(self) -> Optional[str]:
        """CLI：列出存檔，讓使用者輸入序號，回傳該檔 path；Enter 取消回 None。"""
        saves = self.list()
        if not saves:
            print("\n（目前沒有任何存檔可以讀）")
            return None

        self.print_list()
        raw = input("請輸入要讀的序號（或直接 Enter 取消）：").strip()
        if not raw:
            return None
        if not raw.isdigit():
            print("輸入不正確。")
            return None

        i = int(raw)
        if i <= 0 or i > len(saves):
            print("序號超出範圍。")
            return None

        file_name = saves[i - 1].file
        return str(Path(self._saves_dir) / file_name)

    # ----------------------------
    # Save (core)
    # ----------------------------
    def _build_full_snapshot(
        self,
        *,
        session: GameSession,
        case_id: str,
        case_title: str,
        config: GameConfig,
    ) -> Dict[str, Any]:
        snap = session.export_snapshot()
        snap = normalize_snapshot(snap)  # v1/v2 統一
        snap = snapshot_attach_case_and_config(
            snap,
            case_id=case_id,
            case_title=case_title,
            config=config,
        )
        snap = attach_saved_at(snap)
        return snap

    def save_to_path(
        self,
        file_path: str,
        *,
        session: GameSession,
        case_id: str,
        case_title: str,
        config: GameConfig,
    ) -> str:
        snap = self._build_full_snapshot(
            session=session,
            case_id=case_id,
            case_title=case_title,
            config=config,
        )
        save_json(snap, file_path)
        return file_path

    def save_autosave(
        self,
        *,
        session: GameSession,
        case_id: str,
        case_title: str,
        config: GameConfig,
    ) -> str:
        return self.save_to_path(
            self.autosave_path(),
            session=session,
            case_id=case_id,
            case_title=case_title,
            config=config,
        )

    def save_slot(
        self,
        slot: int,
        *,
        session: GameSession,
        case_id: str,
        case_title: str,
        config: GameConfig,
    ) -> str:
        return self.save_to_path(
            self.slot_path(slot),
            session=session,
            case_id=case_id,
            case_title=case_title,
            config=config,
        )

    # ----------------------------
    # Load
    # ----------------------------
    def load_from_file(self, file_path: str) -> Tuple[GameSession, str, dict, GameConfig]:
        snap = load_json(file_path)
        snap = normalize_snapshot(snap)

        case_id = read_case_id(snap)
        if not case_id or case_id not in self._cases:
            raise ValueError("存檔沒有合法的 case id（或案件不存在）")

        config = read_config(snap)

        case = self._cases[case_id]
        nodes = case["nodes"]
        rule = case.get("solve_rule", {}) or {}

        session = restore_session_from_snapshot(
            snapshot=snap,
            nodes=nodes,
            config=config,
            solve_rule=rule,
        )

        self.repair_session_current_if_needed(session=session, case=case)
        return session, case_id, case, config

    def repair_session_current_if_needed(self, *, session: GameSession, case: Dict[str, Any]) -> None:
        if session.current in session.nodes:
            return

        fallback = str(case.get("start") or "").strip()
        if not fallback or fallback not in session.nodes:
            fallback = next(iter(session.nodes.keys()))

        old = session.current
        session.current = fallback
        print(f"\n[提示] 存檔節點已不存在：{old} → 已改為 {fallback}（案件內容可能更新過）")
