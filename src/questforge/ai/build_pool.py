# src/questforge/ai/build_pool.py
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

from questforge.ai.runtime_story_nodes_generator_v1 import RuntimeStoryNodesGeneratorV1


def _now_ts() -> int:
    return int(time.time())


def _write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50, help="how many stories to generate")
    ap.add_argument("--out", type=str, default=".qf_cache/pool", help="output dir")
    ap.add_argument("--seed", type=int, default=None, help="optional base seed")
    args = ap.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    gen = RuntimeStoryNodesGeneratorV1()

    ok = 0
    fail = 0

    for i in range(1, max(1, args.n) + 1):
        forced_case_id = f"pool_{uuid.uuid4().hex[:10]}"
        seed = args.seed
        try:
            pkg = gen.generate(seed=seed, forced_case_id=forced_case_id)
            pkg_dict = asdict(pkg)

            obj = {
                "pkg": pkg_dict,
                "pool_meta": {
                    "created_at": _now_ts(),
                    "model": (os.getenv("QF_STORY_MODEL") or "").strip(),
                    "ai_mode": (os.getenv("AI_MODE") or "").strip(),
                    "forced_case_id": forced_case_id,
                },
            }

            fn = f"{_now_ts()}_{forced_case_id}.json"
            _write_json(out_dir / fn, obj)
            ok += 1
            print(f"[POOL_BUILD] {i}/{args.n} ok -> {fn}", flush=True)
        except Exception as e:
            fail += 1
            print(f"[POOL_BUILD] {i}/{args.n} fail err={e!r}", flush=True)

    print(f"[POOL_BUILD] done ok={ok} fail={fail} out={str(out_dir)}", flush=True)


if __name__ == "__main__":
    main()
