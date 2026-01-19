# src/questforge_server/schemas.py
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


JsonMap = Dict[str, Any]


class StartRequest(BaseModel):
    case_id: Optional[str] = None
    seed: Optional[int] = None


class ChooseRequest(BaseModel):
    session_id: str = Field(..., description="server-side session id")
    choice_index: int = Field(..., description="index in NodeView.choices")


class UiResponse(BaseModel):
    contract: str = Field("ui_contract_v2", description="contract name/version")
    session_id: str
    payload: JsonMap
