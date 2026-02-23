# src/questforge_server/pool/pool_config.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PoolConfig:
    # Minimum ready AI stories you want buffered
    min_ready: int = 2

    # Sample pool folder in repo
    sample_dir: Path = Path("src/questforge/content/sample_pool_json")