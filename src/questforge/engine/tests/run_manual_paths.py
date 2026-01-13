from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from questforge.engine.tests.manual_paths import build_paths, run_path


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser("questforge-engine-manual-paths")
    p.add_argument("--only", nargs="*", default=None, help="Only run specified path names")
    p.add_argument("--quiet", action="store_true", help="No pretty printing checkpoints")
    p.add_argument("--json", action="store_true", help="Output checkpoints in JSON (per path)")
    args = p.parse_args(argv)

    paths = build_paths()
    if args.only:
        allow = set([x.strip() for x in args.only if x and x.strip()])
        paths = [x for x in paths if x.name in allow]

    if not paths:
        print("No paths matched.")
        return 2

    ok = 0
    failed: List[Tuple[str, str]] = []
    report: Dict[str, Any] = {"passed": [], "failed": []}

    for path in paths:
        try:
            # 讓 run_path 回傳 checkpoints，方便 JSON report
            cps = run_path(path, verbose=(not args.quiet), return_checkpoints=True)  # 👈 Day18-E 需要你在 manual_paths.py 小改一下
            ok += 1
            report["passed"].append(path.name)
            if args.json:
                report[path.name] = [asdict(cp) for cp in cps]
        except Exception as e:
            failed.append((path.name, str(e)))
            report["failed"].append({"name": path.name, "error": str(e)})
            if not args.quiet:
                print(f"\n❌ {path.name} FAILED: {e}")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    if not args.quiet:
        print("\n" + "-" * 60)
        print(f"Result: {ok}/{len(paths)} passed")
        if failed:
            print("Failed:")
            for name, err in failed:
                print(f" - {name}: {err}")
        print("-" * 60)

    return 0 if ok == len(paths) else 1


if __name__ == "__main__":
    raise SystemExit(main())
