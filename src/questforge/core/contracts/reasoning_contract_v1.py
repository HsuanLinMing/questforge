from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


CONTRACT_VERSION = "reasoning_contract_v1"


ReasoningLevel = Literal["weak", "ok", "good"]
EndTag = Literal["ending_result", "ending_wrong", "epilogue", "ending_check"]


@dataclass(frozen=True)
class ReasoningSummaryV1:
    version: str = CONTRACT_VERSION

    # context
    case_title: str = ""
    node_id: str = ""
    tag: EndTag = "ending_check"
    turn: int = 0

    # accuse / reason
    accused: str = ""  # suspect id or name
    reason_mode: str = "choice"  # choice/text/voice
    reason_ids: List[str] = field(default_factory=list)
    selected_observations: List[str] = field(default_factory=list)
    reason_text: str = ""
    reason_summary: str = ""

    # evidence
    clues_preview: List[str] = field(default_factory=list)

    # scoring
    level: ReasoningLevel = "weak"
    score: int = 0
    threshold: int = 0
    engine_message: str = ""

    matched_evidence: List[str] = field(default_factory=list)
    missing_key_evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "case_title": self.case_title,
            "node_id": self.node_id,
            "tag": self.tag,
            "turn": int(self.turn),
            "accused": self.accused,
            "reason_mode": self.reason_mode,
            "reason_ids": list(self.reason_ids),
            "selected_observations": list(self.selected_observations),
            "reason_text": self.reason_text,
            "reason_summary": self.reason_summary,
            "clues_preview": list(self.clues_preview),
            "level": self.level,
            "score": int(self.score),
            "threshold": int(self.threshold),
            "engine_message": self.engine_message,
            "matched_evidence": list(self.matched_evidence),
            "missing_key_evidence": list(self.missing_key_evidence),
        }


def _str_list(v: Any) -> List[str]:
    if not isinstance(v, list):
        return []
    out: List[str] = []
    for x in v:
        s = str(x).strip()
        if s:
            out.append(s)
    return out

def ensure_reasoning_contract_v1(meta: Dict[str, Any], *, defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把現有 meta normalize 成 contract v1 的 key set（缺的補預設）。"""
    defaults = defaults or {}
    out: Dict[str, Any] = {}
    out["version"] = CONTRACT_VERSION

    def pick(key: str, fallback: Any) -> Any:
        if key in meta and meta[key] is not None:
            return meta[key]
        if key in defaults and defaults[key] is not None:
            return defaults[key]
        return fallback

    out["case_title"] = str(pick("case_title", ""))
    out["node_id"] = str(pick("node_id", ""))
    out["tag"] = str(pick("tag", "ending_check"))
    out["turn"] = int(pick("turn", 0) or 0)

    out["accused"] = str(pick("accused", ""))
    out["reason_mode"] = str(pick("reason_mode", "choice"))
    out["reason_ids"] = _str_list(pick("reason_ids", []))
    out["selected_observations"] = _str_list(pick("selected_observations", []))
    out["reason_text"] = str(pick("reason_text", ""))
    out["reason_summary"] = str(pick("reason_summary", ""))

    out["clues_preview"] = _str_list(pick("clues_preview", []))

    out["level"] = str(pick("level", "weak"))
    out["score"] = int(pick("score", 0) or 0)
    out["threshold"] = int(pick("threshold", 0) or 0)
    out["engine_message"] = str(pick("engine_message", ""))

    out["matched_evidence"] = _str_list(pick("matched_evidence", []))
    out["missing_key_evidence"] = _str_list(pick("missing_key_evidence", []))

    return out
