from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from questforge.ai.schemas import ResponseRequest, ResponsePackage
from questforge.ai.guard import GuardResult


def log_guard_result(
    *,
    req: ResponseRequest,
    pkg: ResponsePackage,
    gr: GuardResult,
    log_path: str = "logs/ai_guard.jsonl",
    max_text_len: int = 280,
) -> None:
    """Append one JSON line for each AI response + guard result."""
    try:
        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)

        text = (pkg.text or "").strip()
        if max_text_len > 0 and len(text) > max_text_len:
            text = text[:max_text_len] + "…"

        record = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "intent": req.intent,
            "role": req.role,
            "scene_title": getattr(req, "scene_title", None),
            "accused_name": getattr(req, "accused_name", None),
            "ok": gr.ok,
            "errors": list(gr.errors or []),
            "warnings": list(gr.warnings or []),
            "stats": dict(gr.stats or {}),
            "text": text,
        }

        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Day14-A：log 失敗不應該影響遊戲流程
        pass
