# src/questforge_server/progress.py
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional


def _ts() -> str:
    # 只用秒數差，避免時區問題
    return f"{time.time():.3f}"


@dataclass
class ProgressLogger:
    sid: str
    label: str = "START"
    t0: float = 0.0

    def __post_init__(self) -> None:
        self.t0 = time.time()

    def log(self, step: str, **kv: object) -> None:
        dt = time.time() - self.t0
        extra = ""
        if kv:
            extra = " " + " ".join([f"{k}={v}" for k, v in kv.items()])
        print(f"[{self.label}] sid={self.sid[:6]} +{dt:0.2f}s {step}{extra}", flush=True)

    def timed(self, step: str):
        return _Timer(self, step)


class _Timer:
    def __init__(self, p: ProgressLogger, step: str) -> None:
        self.p = p
        self.step = step
        self.t = 0.0

    def __enter__(self):
        self.t = time.time()
        self.p.log(self.step + ":begin")
        return self

    def __exit__(self, exc_type, exc, tb):
        dt = time.time() - self.t
        if exc is None:
            self.p.log(self.step + ":ok", dt=f"{dt:0.2f}s")
        else:
            self.p.log(self.step + ":fail", dt=f"{dt:0.2f}s", err=repr(exc))
        # 不吞例外
        return False
