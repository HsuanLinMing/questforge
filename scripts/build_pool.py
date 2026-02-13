from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from questforge.ai.runtime_story_nodes_generator_v1 import RuntimeStoryNodesGeneratorV1
from questforge.contracts.story_nodes_v1 import story_nodes_package_from_dict
from questforge.contracts.story_nodes_validator_v1 import (
    StoryNodesValidationError,
    validate_story_nodes_v1,
)

REQUIRED_DEFER_CHOICE = "我還不確定，交給大人"


def _pkg_to_dict(pkg: Any) -> Dict[str, Any]:
    """
    將 StoryNodesPackage 轉成可 json dump 的 dict。
    你的 StoryNodesPackage 目前看起來不是 pydantic model（沒有 model_dump/dict/json），
    所以要用「遞迴降階」方式做。
    """
    import dataclasses

    def to_plain(x: Any) -> Any:
        if x is None or isinstance(x, (str, int, float, bool)):
            return x
        if isinstance(x, dict):
            return {str(k): to_plain(v) for k, v in x.items()}
        if isinstance(x, (list, tuple, set)):
            return [to_plain(v) for v in x]

        # dataclass
        if dataclasses.is_dataclass(x):
            return {f.name: to_plain(getattr(x, f.name)) for f in dataclasses.fields(x)}

        # pydantic v2
        if hasattr(x, "model_dump"):
            return to_plain(x.model_dump())
        # pydantic v1
        if hasattr(x, "dict"):
            return to_plain(x.dict())

        # 最後保底：一般 class 用 __dict__
        if hasattr(x, "__dict__"):
            # 避免 private 欄位干擾
            d = {k: v for k, v in vars(x).items() if not str(k).startswith("_")}
            return {str(k): to_plain(v) for k, v in d.items()}

        raise TypeError(f"Cannot serialize type: {type(x)}")

    out = to_plain(pkg)
    if not isinstance(out, dict):
        raise TypeError(f"pkg to dict not a dict: {type(out)}")
    return out


def _patch_final_accuse_choice4(data: Dict[str, Any]) -> bool:
    """
    強制把 final_accuse 第4個 choice 覆寫成指定句子，避免 validator 卡死。
    回傳是否有做 patch。
    """
    nodes = data.get("nodes")
    if not isinstance(nodes, dict):
        return False

    node = nodes.get("final_accuse")
    if not isinstance(node, dict):
        return False

    choices = node.get("choices")
    if not isinstance(choices, list):
        return False

    # 不夠就補到 4
    while len(choices) < 4:
        choices.append({"index": len(choices), "text": "", "next": "scene_10_ending_defer"})

    c4 = choices[3]
    if not isinstance(c4, dict):
        c4 = {"index": 3, "text": "", "next": "scene_10_ending_defer"}
        choices[3] = c4

    changed = (str(c4.get("text") or "") != REQUIRED_DEFER_CHOICE)
    c4["text"] = REQUIRED_DEFER_CHOICE
    c4["index"] = 3
    c4.setdefault("next", "scene_10_ending_defer")

    node["choices"] = choices[:4]
    nodes["final_accuse"] = node
    data["nodes"] = nodes
    return changed


def _dump_fail(out_failed_dir: Path, i: int, err: Exception, raw: Optional[Dict[str, Any]] = None) -> None:
    ts = int(time.time())
    meta = {"i": i, "ts": ts, "error": repr(err)}
    (out_failed_dir / f"fail_{ts}_{i}_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if raw is not None:
        (out_failed_dir / f"fail_{ts}_{i}_raw.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--out", type=str, default=".qf_cache/pool")
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--max_attempts", type=int, default=6)  # 每篇故事最多嘗試幾次（外層）
    args = ap.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    failed_dir = out_dir / "_failed"
    failed_dir.mkdir(parents=True, exist_ok=True)

    gen = RuntimeStoryNodesGeneratorV1()

    ok = 0
    i = 0
    while ok < args.n:
        attempt_seed = None if args.seed is None else (args.seed + i)
        case_id_hint = f"pool_{int(time.time())}_{ok}"

        try:
            pkg = gen.generate(seed=attempt_seed, forced_case_id=case_id_hint)
            data = _pkg_to_dict(pkg)

            # ✅ patch 之後，用「package」去 validate（validate 期待的是 StoryNodesPackage）
            patched = _patch_final_accuse_choice4(data)
            pkg2 = story_nodes_package_from_dict(data)
            validate_story_nodes_v1(pkg2)

            # ✅ 寫入 pool 目錄（這裡才是你要的 pool）
            meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
            case_id = str((meta or {}).get("case_id") or case_id_hint).strip() or case_id_hint
            ts = int(time.time())
            fp = out_dir / f"{case_id}_{ts}_{ok}.json"
            fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

            ok += 1
            print(f"[POOL] ok {ok}/{args.n} patched={patched} -> {fp}", flush=True)

            if args.sleep > 0:
                time.sleep(args.sleep)

        except StoryNodesValidationError as e:
            print(f"[POOL] validation fail ok={ok} i={i} err={e}", flush=True)
            _dump_fail(failed_dir, i=i, err=e)
        except Exception as e:
            print(f"[POOL] fail ok={ok} i={i} err={e!r}", flush=True)
            # 有些失敗你會想看 raw（如果已經有 data）
            _dump_fail(failed_dir, i=i, err=e)

        i += 1
        if i > args.n * args.max_attempts:
            raise RuntimeError(f"Too many failures: ok={ok}/{args.n}, tried={i}")

    print(f"[POOL] done ok={ok}/{args.n} dir={out_dir}", flush=True)


if __name__ == "__main__":
    main()
