# src/questforge/ai/ai_client.py
from __future__ import annotations

import os
from abc import ABC, abstractmethod

from questforge.ai.schemas import ResponsePackage, ResponseRequest, StoryPackage


class AiClient(ABC):
    """AI boundary interface.

    - Story generation: produce structured StoryPackage.
    - Response generation: produce short safe ResponsePackage (whitelist intent).
    """

    @abstractmethod
    def generate_story(self) -> StoryPackage:
        raise NotImplementedError

    @abstractmethod
    def generate_response(self, req: ResponseRequest) -> ResponsePackage:
        raise NotImplementedError


def build_ai_client() -> AiClient:
    """Factory: choose AI client by env var.

    AI_MODE:
      - "mock" (default): deterministic / dev friendly
      - "real": wire-ready client (Day14-B), may still be stubbed
    """
    mode = (os.getenv("AI_MODE") or "mock").strip().lower()

    if mode == "real":
        from questforge.ai.real_ai import RealAiClient
        return RealAiClient()

    from questforge.ai.mock_ai import MockAiClient

    return MockAiClient()
