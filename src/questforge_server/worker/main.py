from __future__ import annotations

import hashlib
import json
import os
import time
import traceback
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple

from questforge.ai.runtime_story_nodes_generator_v1 import RuntimeStoryNodesGeneratorV1
from questforge.contracts.story_nodes_validator_v1 import validate_story_nodes_v1

from questforge_server.pool.queue_client_upstash import UpstashRedisRest
from questforge_server.pool.jobs import GenerateAiStoryJob
from questforge_server.pool.story_storage_local import LocalStoryStorage, LocalStoryStorageConfig

from questforge_server.tts_service import synthesize_to_wav
from questforge.ai.tts.voice_map import voice_for_role


# ----------------------------
# Role mapping
# StoryNodes v1 narration.role: narrator/feifei/lele/teacher/student...
# voice_map expects: 旁白/霏霏/樂樂/老師 (or narrator/teacher/child_female/child_male)
# ----------------------------

_ROLE_TO_CN = {
    "narrator": "旁白",
    "feifei": "霏霏",
    "lele": "樂樂",
    "teacher": "老師",
    "student": "旁白",
}

_ALLOWED_VOICE_KEYS = {
    "旁白",
    "霏霏",
    "樂樂",
    "老師",
    "narrator",
    "teacher",
    "child_female",
    "child_male",
}


def _voice_key_for_role(role: str) -> str:
    r = (role or "").strip()
    if not r:
        return "旁白"
    # already chinese
    if r in ("旁白", "霏霏", "樂樂", "老師"):
        return r
    # normalized
    return _ROLE_TO_CN.get(r, "旁白")


def _voice_speed_for_voice_key(voice_key: str) -> float:
    if voice_key in ("旁白", "narrator"):
        return 0.95
    if voice_key in ("霏霏", "child_female"):
        return 1.05
    if voice_key in ("樂樂", "child_male"):
        return 1.12
    if voice_key in ("老師", "teacher"):
        return 0.98
    return 1.0


def _tts_enabled() -> bool:
    v = (os.getenv("QF_TTS_ENABLED") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


# ----------------------------
# Narration extraction
# ----------------------------

def _iter_narration_items_from_node(node: Any) -> List[Tuple[str, str]]:
    """
    Return list of (role, text) from a node.
    Supports:
      - StoryNode model: node.narration is List[NarrationItem] (role,text)
      - dict node: narration may be str OR list[dict] OR list[tuple]
    """
    if node is None:
        return []

    # 1) StoryNode-like (pydantic model)
    narration = getattr(node, "narration", None)
    if narration is not None:
        out: List[Tuple[str, str]] = []
        # List[NarrationItem]
        if isinstance(narration, list):
            for it in narration:
                role = getattr(it, "role", None)
                text = getattr(it, "text", None)
                if role is None and isinstance(it, dict):
                    role = it.get("role")
                    text = it.get("text")
                role_s = (role or "").strip()
                text_s = (text or "").strip()
                if text_s:
                    out.append((role_s or "narrator", text_s))
            return out

        # if someone stored as string
        if isinstance(narration, str) and narration.strip():
            return _items_from_narration_text(narration)

    # 2) dict node
    if isinstance(node, dict):
        n = node.get("narration")
        if isinstance(n, str) and n.strip():
            return _items_from_narration_text(n)

        if isinstance(n, list):
            out2: List[Tuple[str, str]] = []
            for it in n:
                if isinstance(it, dict):
                    role_s = (it.get("role") or "").strip() or "narrator"
                    text_s = (it.get("text") or "").strip()
                    if text_s:
                        out2.append((role_s, text_s))
                elif isinstance(it, (list, tuple)) and len(it) >= 2:
                    role_s = (str(it[0]) or "").strip() or "narrator"
                    text_s = (str(it[1]) or "").strip()
                    if text_s:
                        out2.append((role_s, text_s))
            return out2

    return []


def _items_from_narration_text(narration: str) -> List[Tuple[str, str]]:
    """
    Parse legacy "角色：內容" paragraphs separated by blank lines.
    """
    paras = [x.strip() for x in (narration or "").split("\n\n") if x.strip()]
    out: List[Tuple[str, str]] = []
    for p in paras:
        first_line, *rest_lines = p.splitlines()
        first_line = first_line.strip()
        rest_text = "\n".join([x.strip() for x in rest_lines]).strip()

        if "：" in first_line:
            role, rest = first_line.split("：", 1)
            role = role.strip()
            text0 = (rest or "").strip()
            text = text0
            if rest_text:
                text = (text0 + "\n" + rest_text).strip()
            if text:
                out.append((role, text))
            else:
                out.append((role, p))
        else:
            out.append(("旁白", p))
    return out


def _build_view_narration(items: List[Tuple[str, str]]) -> str:
    """
    Build the view narration string used for view_fp hashing.
    Must match routes_game’s behavior as much as possible: "旁白：...\\n\\n霏霏：..."
    """
    lines: List[str] = []
    for role, text in items:
        cn = _voice_key_for_role(role)
        t = (text or "").strip()
        if not t:
            continue
        lines.append(f"{cn}：{t}")
    return "\n\n".join(lines)


def _safe_validate_pkg(pkg: Any) -> None:
    """
    Validator expects a dict-like package.
    """
    if hasattr(pkg, "to_dict"):
        validate_story_nodes_v1(pkg.to_dict())
        return
    if hasattr(pkg, "model_dump"):
        validate_story_nodes_v1(pkg.model_dump())
        return
    if hasattr(pkg, "dict"):
        validate_story_nodes_v1(pkg.dict())
        return
    validate_story_nodes_v1(pkg)


def _prewarm_tts_for_story(*, storage: LocalStoryStorage, story_id: str, pkg: Any) -> int:
    """
    Generate pooled TTS for all nodes into:
      .qf_cache/pool_ai/tts/<story_id>/<view_fp>/*.wav

    view_fp = sha1("v2|<view_narration>")
    """
    out_story_dir = storage.tts_story_dir(story_id)
    out_story_dir.mkdir(parents=True, exist_ok=True)

    nodes = getattr(pkg, "nodes", None) or {}
    clips = 0
    nodes_hit = 0

    for node_id, node in (nodes or {}).items():
        items = _iter_narration_items_from_node(node)
        if not items:
            continue

        nodes_hit += 1
        view_narration = _build_view_narration(items)
        if not view_narration.strip():
            continue

        view_fp = hashlib.sha1(("v2|" + view_narration).encode("utf-8")).hexdigest()
        out_dir = out_story_dir / view_fp
        out_dir.mkdir(parents=True, exist_ok=True)

        node_clips = 0
        for role, text in items:
            voice_key = _voice_key_for_role(role)
            if voice_key not in _ALLOWED_VOICE_KEYS:
                voice_key = "旁白"

            spoken_text = (text or "").strip()
            if not spoken_text:
                continue

            profile = voice_for_role(voice_key)
            speed = _voice_speed_for_voice_key(voice_key)

            r = synthesize_to_wav(
                text=spoken_text,
                out_dir=out_dir,
                voice=profile.voice,
                instructions=profile.instructions,
                speed=speed,
            )
            if r is not None:
                clips += 1
                node_clips += 1

        print(
            f"[WORKER][TTS] node={node_id} view_fp={view_fp[:8]} out={out_dir} clips={node_clips}",
            flush=True,
        )

    print(f"[WORKER][TTS] story_id={story_id[:8]} nodes_hit={nodes_hit} total_clips={clips}", flush=True)
    return clips


def main() -> None:
    redis = UpstashRedisRest.from_env()
    jobs_key = "qf:jobs"
    ready_key = "qf:ready_ai"
    dead_key = "qf:dead"

    storage = LocalStoryStorage(LocalStoryStorageConfig(root_dir=Path(".qf_cache/pool_ai")))
    gen = RuntimeStoryNodesGeneratorV1()

    print("[WORKER] start", flush=True)

    backoff = 1.0
    max_backoff = 12.0
    last_heartbeat = time.time()

    while True:
        raw: Optional[str] = None
        try:
            raw = redis.rpop(jobs_key)

            # ----- idle -----
            if not raw:
                now = time.time()
                if now - last_heartbeat >= 30:
                    last_heartbeat = now
                    print("[WORKER] idle ok (no jobs)", flush=True)
                time.sleep(1.0)
                backoff = 1.0
                continue

            backoff = 1.0

            job = GenerateAiStoryJob.from_json(raw)
            if job.kind != "gen_ai_story_v1" or not job.story_id:
                print(f"[WORKER] skip bad job={raw}", flush=True)
                redis.lpush(dead_key, raw)
                continue

            story_id = job.story_id
            sid8 = story_id[:8]
            print(f"[WORKER] job story_id={sid8} seed={job.seed}", flush=True)

            # ----- de-dupe -----
            story_path = storage.story_json_path(story_id)
            if story_path.exists():
                print(f"[WORKER] story exists, publish ready story_id={sid8}", flush=True)
                redis.lpush(ready_key, story_id)
                continue

            # 1) generate
            pkg = gen.generate(seed=job.seed, forced_case_id=f"ai_pool_{sid8}")

            # 2) validate
            _safe_validate_pkg(pkg)

            # 3) store json
            storage.put_story_pkg(story_id, pkg)

            # 4) prewarm tts
            if _tts_enabled():
                clips = _prewarm_tts_for_story(storage=storage, story_id=story_id, pkg=pkg)
                print(f"[WORKER] tts done story_id={sid8} clips={clips}", flush=True)
            else:
                print(f"[WORKER] tts disabled story_id={sid8}", flush=True)

            # 5) publish ready
            redis.lpush(ready_key, story_id)
            print(f"[WORKER] ready ok story_id={sid8}", flush=True)

        except Exception as e:
            tb = traceback.format_exc()
            print(f"[WORKER] error {e!r}", flush=True)
            print(tb, flush=True)

            # push structured dead payload
            try:
                dead_payload = {
                    "ts": int(time.time()),
                    "error": repr(e),
                    "traceback": tb[-4000:],
                    "raw_job": raw,
                }
                redis.lpush(dead_key, json.dumps(dead_payload, ensure_ascii=False))
            except Exception:
                pass

            time.sleep(backoff)
            backoff = min(max_backoff, backoff * 1.6)


if __name__ == "__main__":
    main()