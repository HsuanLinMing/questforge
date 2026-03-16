from __future__ import annotations

import os

from openai import OpenAI


_BAD_ENV_CHARS = ("\u2028", "\u2029", "\ufeff")


def clean_openai_api_key(value: str | None) -> str:
    key = value or ""
    for ch in _BAD_ENV_CHARS:
        key = key.replace(ch, "")
    return key.strip()


def get_clean_openai_api_key() -> str:
    key = clean_openai_api_key(os.environ.get("OPENAI_API_KEY"))
    if key and key != os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = key
    return key


def build_openai_client(**kwargs: object) -> OpenAI:
    api_key = clean_openai_api_key(kwargs.pop("api_key", None) or os.environ.get("OPENAI_API_KEY"))
    if api_key:
        return OpenAI(api_key=api_key, **kwargs)
    return OpenAI(**kwargs)
