from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from questforge.core.models import GameConfig

SAVES_DIR = "saves"
DEFAULT_SAVE_PATH = str(Path(SAVES_DIR) / "autosave.json")
SLOT_PATTERN = re.compile(r"^slot_(\d+)\.json$")


def ensure_parent_dir(file_path: str) -> Path:
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def save_json(data: Dict[str, Any], file_path: str = DEFAULT_SAVE_PATH) -> None:
    path = ensure_parent_dir(file_path)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(file_path: str = DEFAULT_SAVE_PATH) -> Dict[str, Any]:
    path = Path(file_path)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def snapshot_attach_case_and_config(
    snapshot: Dict[str, Any],
    *,
    case_id: str,
    case_title: str,
    config: GameConfig,
) -> Dict[str, Any]:
    """把 case/config metadata 塞進 snapshot（不改 GameSession snapshot 核心格式）。"""
    out = dict(snapshot)  # copy
    out["case"] = {"id": case_id, "title": case_title}
    out["config"] = {
        "enable_quiz": bool(config.enable_quiz),
        "quiz_can_skip": bool(config.quiz_can_skip),
    }
    return out


def read_case_id(snapshot: Dict[str, Any]) -> str:
    return str((snapshot.get("case") or {}).get("id") or "").strip()


def read_config(snapshot: Dict[str, Any]) -> GameConfig:
    cfg = snapshot.get("config") or {}
    return GameConfig(
        enable_quiz=bool(cfg.get("enable_quiz", False)),
        quiz_can_skip=bool(cfg.get("quiz_can_skip", True)),
    )


def slot_path(slot: int) -> str:
    slot = int(slot)
    if slot <= 0:
        raise ValueError("slot 必須 >= 1")
    return str(Path(SAVES_DIR) / f"slot_{slot}.json")


def attach_saved_at(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """寫入存檔時間（UTC ISO）。"""
    out = dict(snapshot)
    out["saved_at"] = datetime.now(timezone.utc).isoformat()
    return out


def _read_meta(snapshot: Dict[str, Any], *, file_name: str) -> Dict[str, Any]:
    case = snapshot.get("case") or {}
    cfg = snapshot.get("config") or {}
    state = snapshot.get("state") or {}

    return {
        "file": file_name,
        "case_id": str(case.get("id") or "").strip(),
        "case_title": str(case.get("title") or "").strip(),
        "turn": int(state.get("turn", 0) or 0),
        "saved_at": str(snapshot.get("saved_at") or "").strip(),
        "enable_quiz": bool(cfg.get("enable_quiz", False)),
    }


def list_saves(dir_path: str = SAVES_DIR) -> List[Dict[str, Any]]:
    """列出 saves/ 下可用的存檔（autosave + slot_n）。"""
    p = Path(dir_path)
    if not p.exists():
        return []

    files: List[Path] = []
    autosave = p / "autosave.json"
    if autosave.exists():
        files.append(autosave)

    for f in p.glob("slot_*.json"):
        files.append(f)

    def key_fn(fp: Path) -> Tuple[int, int]:
        if fp.name == "autosave.json":
            return (0, 0)
        m = SLOT_PATTERN.match(fp.name)
        if m:
            return (1, int(m.group(1)))
        return (9, 999999)

    files.sort(key=key_fn)

    out: List[Dict[str, Any]] = []
    for fp in files:
        try:
            snap = load_json(str(fp))
            out.append(_read_meta(snap, file_name=fp.name))
        except Exception:
            out.append({"file": fp.name, "broken": True})
    return out


LATEST_SNAPSHOT_VERSION = 2


def normalize_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    snap = dict(snapshot)
    ver = int(snap.get("version", 0) or 0)

    # v0 -> v1（舊存檔可能沒有 version/state/session 結構）
    if ver <= 0:
        snap.setdefault("state", {})
        snap.setdefault("session", {"current": ""})
        snap["version"] = 1
        ver = 1

    # v1 -> v2（目前 v2 其實跟 v1 結構相容，只是版本號不同）
    if ver == 1:
        # 先保留相容：不強制改動內容，但你可選擇升到 v2
        # 為了統一，我們直接升版
        snap["version"] = 2
        ver = 2

    if ver > LATEST_SNAPSHOT_VERSION:
        # 程式太舊讀不到新存檔：交給上層報錯即可
        pass

    return snap


def infer_case_id(snapshot: Dict[str, Any], cases: Dict[str, Dict[str, Any]]) -> str:
    # 1) 正常：有 case.id
    cid = read_case_id(snapshot)
    if cid:
        return cid

    # 2) 舊檔：只有 case.title（或根本沒有 case 區塊）
    title = str((snapshot.get("case") or {}).get("title") or "").strip()
    if not title:
        return ""

    # 用 title 反查 CASES
    matches = [
        k for k, c in cases.items() if str(c.get("title") or "").strip() == title
    ]
    if len(matches) == 1:
        return matches[0]

    # 多個同名或找不到就放棄（避免錯案）
    return ""
