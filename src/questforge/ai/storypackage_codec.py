# src/questforge/ai/storypackage_codec.py
from __future__ import annotations

from typing import Any, Dict, List

from questforge.ai.schemas import (
    StoryPackage,
    StoryCharacter,
    StoryScene,
    StoryObservation,
)


class StoryPackageParseError(RuntimeError):
    pass


def storypackage_from_dict(data: Any) -> StoryPackage:
    if not isinstance(data, dict):
        raise StoryPackageParseError("root_not_object")

    # ---- required top-level fields ----
    required = [
        "case_id",
        "title",
        "prologue",
        "characters",
        "scenes",
        "cooldown_dialogue",
        "teacher_scene",
        "open_ending",
    ]
    missing = [k for k in required if not data.get(k)]
    if missing:
        raise StoryPackageParseError(f"missing_fields:{missing}")

    case_id = str(data["case_id"]).strip()
    title = str(data["title"]).strip()
    prologue = str(data["prologue"]).strip()
    cooldown_dialogue = str(data["cooldown_dialogue"]).strip()
    teacher_scene = str(data["teacher_scene"]).strip()
    open_ending = str(data["open_ending"]).strip()

    tags_raw = data.get("tags") or []
    tags: List[str] = []
    if isinstance(tags_raw, list):
        for x in tags_raw:
            s = str(x or "").strip()
            if s:
                tags.append(s)

    # ---- characters ----
    chars_raw = data.get("characters") or []
    if not isinstance(chars_raw, list) or not chars_raw:
        raise StoryPackageParseError("characters_invalid")

    characters: List[StoryCharacter] = []
    for i, c in enumerate(chars_raw):
        if not isinstance(c, dict):
            raise StoryPackageParseError(f"character_{i}_not_object")
        name = str(c.get("name") or "").strip()
        role = str(c.get("role") or "").strip()
        notes = str(c.get("notes") or "").strip()
        if not name or not role:
            raise StoryPackageParseError(f"character_{i}_missing_name_or_role")
        characters.append(StoryCharacter(name=name, role=role, notes=notes))

    # ---- scenes ----
    scenes_raw = data.get("scenes") or []
    if not isinstance(scenes_raw, list) or not scenes_raw:
        raise StoryPackageParseError("scenes_invalid")

    scenes: List[StoryScene] = []
    for si, s in enumerate(scenes_raw):
        if not isinstance(s, dict):
            raise StoryPackageParseError(f"scene_{si}_not_object")
        stitle = str(s.get("title") or "").strip()
        narration = str(s.get("narration") or "").strip()
        if not stitle or not narration:
            raise StoryPackageParseError(f"scene_{si}_missing_title_or_narration")

        obs_list: List[StoryObservation] = []
        obs_raw = s.get("observations") or []
        if obs_raw is not None:
            if not isinstance(obs_raw, list):
                raise StoryPackageParseError(f"scene_{si}_observations_not_list")
            for oi, o in enumerate(obs_raw):
                if not isinstance(o, dict):
                    raise StoryPackageParseError(f"scene_{si}_obs_{oi}_not_object")
                text = str(o.get("text") or "").strip()
                if text:
                    obs_list.append(StoryObservation(text=text))

        scenes.append(StoryScene(title=stitle, narration=narration, observations=obs_list))

    return StoryPackage(
        case_id=case_id,
        title=title,
        prologue=prologue,
        characters=characters,
        scenes=scenes,
        cooldown_dialogue=cooldown_dialogue,
        teacher_scene=teacher_scene,
        open_ending=open_ending,
        tags=tags,
    )
