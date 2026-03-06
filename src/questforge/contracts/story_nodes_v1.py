# src/questforge/contracts/story_nodes_v1.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Union

Role = Literal["narrator", "feifei", "lele", "teacher", "student"]
SchemaVersion = Literal["v1"]

@dataclass
class NarrationItem:
    role: Role
    text: str

@dataclass
class ChoiceItem:
    text: str
    next: str
    enabled: bool = True
    tag: str = ""

@dataclass
class StoryNode:
    title: str
    narration: List[NarrationItem]
    choices: List[ChoiceItem]
    next: Optional[str] = None
    solution_index: Optional[int] = None
    can_replay: Optional[bool] = None
    can_quit: Optional[bool] = None

@dataclass
class StoryMeta:
    schema_version: SchemaVersion
    case_id: str
    title: str
    tags: List[str] = field(default_factory=list)

@dataclass
class StoryNodesPackage:
    meta: StoryMeta
    nodes: Dict[str, StoryNode]


# ----------------------------
# Helpers: narration coercion
# ----------------------------

_ROLE_MAP_ZH = {
    "旁白": "narrator",
    "霏霏": "feifei",
    "樂樂": "lele",
    "老师": "teacher",
    "老師": "teacher",
    "同學": "student",
    "学生": "student",
}

def _split_paragraphs(s: str) -> List[str]:
    return [x.strip() for x in (s or "").split("\n\n") if x.strip()]

def _parse_role_text(p: str) -> NarrationItem:
    s = (p or "").strip()
    if not s:
        return NarrationItem(role="narrator", text="")

    # 允許「角色：內容」
    if "：" in s:
        r, t = s.split("：", 1)
        r = r.strip()
        t = (t or "").strip()
        role = _ROLE_MAP_ZH.get(r, None)
        if role and t:
            return NarrationItem(role=role, text=t)

    return NarrationItem(role="narrator", text=s)

def _coerce_narration(raw: Any) -> List[NarrationItem]:
    # ✅ 正常：list[dict]
    if isinstance(raw, list):
        out: List[NarrationItem] = []
        for it in raw:
            if isinstance(it, dict):
                role = it.get("role")
                text = it.get("text")
                if isinstance(role, str) and isinstance(text, str):
                    out.append(NarrationItem(role=role, text=text))
                else:
                    # dict 但欄位怪 → 當旁白
                    out.append(NarrationItem(role="narrator", text=str(text or "")))
            elif isinstance(it, str):
                # ✅ list[str]：每段當一個 narration item（允許角色：）
                out.append(_parse_role_text(it))
            else:
                out.append(NarrationItem(role="narrator", text=str(it)))
        return [x for x in out if (x.text or "").strip()]

    # ✅ narration 是單一字串（你現在遇到的狀況）
    if isinstance(raw, str):
        paras = _split_paragraphs(raw)
        items = [_parse_role_text(p) for p in paras]
        return [x for x in items if (x.text or "").strip()]

    # 其他型別：硬轉
    if raw is None:
        return []
    return [NarrationItem(role="narrator", text=str(raw))]


def story_nodes_package_from_dict(d: Dict[str, Any]) -> StoryNodesPackage:
    meta_d = d.get("meta") or {}
    nodes_d = d.get("nodes") or {}

    meta = StoryMeta(
        schema_version=meta_d.get("schema_version") or "v1",
        case_id=str(meta_d.get("case_id") or ""),
        title=str(meta_d.get("title") or ""),
        tags=list(meta_d.get("tags") or []),
    )

    if not isinstance(nodes_d, dict):
        raise TypeError("nodes must be an object")

    nodes: Dict[str, StoryNode] = {}
    for node_id, nd in nodes_d.items():
        if not isinstance(nd, dict):
            raise TypeError(f"node {node_id} must be object")

        narration_items = _coerce_narration(nd.get("narration"))

        # choices 必須是 list[dict]，但容錯一下（避免模型輸出 list[str]）
        choices_raw = nd.get("choices") or []
        choices: List[ChoiceItem] = []
        if isinstance(choices_raw, list):
            for c in choices_raw:
                if isinstance(c, dict):
                    choices.append(
                        ChoiceItem(
                            text=str(c.get("text") or ""),
                            next=str(c.get("next") or ""),
                            enabled=bool(c.get("enabled", True)),
                            tag=str(c.get("tag") or ""),
                        )
                    )
                elif isinstance(c, str):
                    # 真的遇到 list[str]：先塞 next 空字串，validator 會抓到
                    choices.append(ChoiceItem(text=c, next=""))
        else:
            raise TypeError(f"node {node_id}.choices must be list")

        nodes[str(node_id)] = StoryNode(
            title=str(nd.get("title") or ""),
            narration=narration_items,
            choices=choices,
            next=nd.get("next"),
            solution_index=nd.get("solution_index"),
            can_replay=nd.get("can_replay"),
            can_quit=nd.get("can_quit"),
        )

    return StoryNodesPackage(meta=meta, nodes=nodes)


# src/questforge/contracts/story_nodes_v1.py

def _coerce_int01_2(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if s.isdigit():
            return int(s)
    return None


def _coerce_bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "yes", "y", "on"):
            return True
        if s in ("0", "false", "no", "n", "off"):
            return False
    return None


def _unwrap_story_nodes_root(d: Dict[str, Any]) -> Dict[str, Any]:
    # 允許模型包一層 {"STORY_NODES": {...}} 或 {"story_nodes": {...}}
    if isinstance(d, dict):
        for k in ("STORY_NODES", "story_nodes", "storyNodes"):
            v = d.get(k)
            if isinstance(v, dict) and ("nodes" in v or "meta" in v):
                return v
    return d


def story_nodes_package_from_dict(d: Dict[str, Any]) -> StoryNodesPackage:
    d = _unwrap_story_nodes_root(d)

    meta_d = d.get("meta") or {}
    nodes_d = d.get("nodes") or {}

    # schema_version 容錯：有些模型會吐 version / schemaVersion
    schema_v = (
        meta_d.get("schema_version")
        or meta_d.get("schemaVersion")
        or meta_d.get("version")
        or "v1"
    )

    meta = StoryMeta(
        schema_version=("v1" if str(schema_v).startswith("v1") else "v1"),
        case_id=str(meta_d.get("case_id") or meta_d.get("caseId") or ""),
        title=str(meta_d.get("title") or ""),
        tags=list(meta_d.get("tags") or []),
    )

    if not isinstance(nodes_d, dict):
        raise TypeError("nodes must be an object")

    nodes: Dict[str, StoryNode] = {}
    for node_id, nd in nodes_d.items():
        if not isinstance(nd, dict):
            raise TypeError(f"node {node_id} must be object")

        narration_items = _coerce_narration(nd.get("narration"))

        choices_raw = nd.get("choices") or []
        choices: List[ChoiceItem] = []
        if isinstance(choices_raw, list):
            for c in choices_raw:
                if isinstance(c, dict):
                    choices.append(
                        ChoiceItem(
                            text=str(c.get("text") or ""),
                            next=str(c.get("next") or ""),
                            enabled=bool(c.get("enabled", True)),
                            tag=str(c.get("tag") or ""),
                        )
                    )
                elif isinstance(c, str):
                    choices.append(ChoiceItem(text=c, next=""))
        else:
            raise TypeError(f"node {node_id}.choices must be list")

        sol = _coerce_int01_2(nd.get("solution_index"))
        can_replay = _coerce_bool(nd.get("can_replay"))
        can_quit = _coerce_bool(nd.get("can_quit"))

        nodes[str(node_id)] = StoryNode(
            title=str(nd.get("title") or ""),
            narration=narration_items,
            choices=choices,
            next=nd.get("next"),
            solution_index=sol,
            can_replay=can_replay,
            can_quit=can_quit,
        )

    return StoryNodesPackage(meta=meta, nodes=nodes)
