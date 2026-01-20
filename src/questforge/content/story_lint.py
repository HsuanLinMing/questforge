from __future__ import annotations

"""Story lint (Narration-only).

目標：只做結構/流程檢查，不評價文筆。

檢查內容：
- node 必填 title
- narration 建議必填；若只寫 beats 會提出 warning
- choices 格式/next 指向
- start node 是否存在
- quit node 建議存在
- 找出不可達節點（unreachable）

手動跑：

  python -m questforge.content.story_lint

或在 cases.py 啟動時自動驗證（搭配 validator.py）。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class LintFinding:
    level: str  # "error" | "warn"
    code: str
    message: str
    case_id: str = ""
    node_id: str = ""


@dataclass
class LintReport:
    errors: List[LintFinding] = field(default_factory=list)
    warnings: List[LintFinding] = field(default_factory=list)

    def add(self, f: LintFinding) -> None:
        if f.level == "error":
            self.errors.append(f)
        else:
            self.warnings.append(f)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_text(self) -> str:
        lines: List[str] = []
        for f in self.errors:
            where = _where(f.case_id, f.node_id)
            lines.append(f"❌ {f.code}{where}: {f.message}")
        for f in self.warnings:
            where = _where(f.case_id, f.node_id)
            lines.append(f"⚠️  {f.code}{where}: {f.message}")
        return "\n".join(lines).strip()


def _where(case_id: str, node_id: str) -> str:
    parts: List[str] = []
    if case_id:
        parts.append(f"case={case_id}")
    if node_id:
        parts.append(f"node={node_id}")
    return f" ({', '.join(parts)})" if parts else ""


def _is_str(x: Any) -> bool:
    return isinstance(x, str)


def _is_list(x: Any) -> bool:
    return isinstance(x, list)


def _is_dict(x: Any) -> bool:
    return isinstance(x, dict)


def _norm_id(s: str) -> str:
    return (s or "").strip()


def _iter_choice_dicts(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = node.get("choices")
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for c in raw:
        if isinstance(c, dict):
            out.append(c)
    return out


def lint_story_nodes(
    *,
    case_id: str,
    title: str,
    nodes: Dict[str, Any],
    start: str,
    solve_rule: Optional[Dict[str, Any]] = None,
) -> LintReport:
    rpt = LintReport()
    solve_rule = solve_rule or {}

    if not isinstance(nodes, dict) or not nodes:
        rpt.add(
            LintFinding(
                level="error",
                code="E_CASE_NODES_EMPTY",
                message="nodes 必須是非空 dict",
                case_id=case_id,
            )
        )
        return rpt

    start = _norm_id(start)
    if not start:
        rpt.add(
            LintFinding(
                level="error",
                code="E_START_EMPTY",
                message="start 不能是空字串",
                case_id=case_id,
            )
        )
    elif start not in nodes:
        rpt.add(
            LintFinding(
                level="error",
                code="E_START_NOT_FOUND",
                message=f"start='{start}' 不在 nodes 裡",
                case_id=case_id,
            )
        )

    # node-level checks
    for nid, node in nodes.items():
        if not _is_dict(node):
            rpt.add(
                LintFinding(
                    level="error",
                    code="E_NODE_NOT_DICT",
                    message="node 必須是 dict",
                    case_id=case_id,
                    node_id=str(nid),
                )
            )
            continue

        t = (node.get("title") or "").strip()
        if not t:
            rpt.add(
                LintFinding(
                    level="error",
                    code="E_TITLE_EMPTY",
                    message="title 必填且不可為空",
                    case_id=case_id,
                    node_id=str(nid),
                )
            )

        narration = (node.get("narration") or "").strip()
        beats = node.get("beats")
        if not narration:
            if beats is not None:
                rpt.add(
                    LintFinding(
                        level="warn",
                        code="W_USE_BEATS",
                        message="narration 為空但 beats 存在：建議轉成 narration-only",
                        case_id=case_id,
                        node_id=str(nid),
                    )
                )
            else:
                rpt.add(
                    LintFinding(
                        level="warn",
                        code="W_NARRATION_EMPTY",
                        message="narration 為空：UI 會顯得很突兀",
                        case_id=case_id,
                        node_id=str(nid),
                    )
                )

        # choices must be list (can be empty)
        if "choices" not in node:
            rpt.add(
                LintFinding(
                    level="warn",
                    code="W_CHOICES_MISSING",
                    message="choices 欄位缺少：建議至少提供 []",
                    case_id=case_id,
                    node_id=str(nid),
                )
            )
            continue

        raw_choices = node.get("choices")
        if not isinstance(raw_choices, list):
            rpt.add(
                LintFinding(
                    level="error",
                    code="E_CHOICES_NOT_LIST",
                    message="choices 必須是 list",
                    case_id=case_id,
                    node_id=str(nid),
                )
            )
            continue

        for i, c in enumerate(raw_choices, start=1):
            if not isinstance(c, dict):
                rpt.add(
                    LintFinding(
                        level="error",
                        code="E_CHOICE_NOT_DICT",
                        message=f"choice[{i}] 必須是 dict",
                        case_id=case_id,
                        node_id=str(nid),
                    )
                )
                continue

            text = (c.get("text") or "").strip()
            if not text:
                rpt.add(
                    LintFinding(
                        level="error",
                        code="E_CHOICE_TEXT_EMPTY",
                        message=f"choice[{i}].text 必填",
                        case_id=case_id,
                        node_id=str(nid),
                    )
                )

            nxt = _norm_id(c.get("next") or "")
            if not nxt:
                rpt.add(
                    LintFinding(
                        level="warn",
                        code="W_CHOICE_NEXT_EMPTY",
                        message=f"choice[{i}].next 為空：會被視為『到此結束』",
                        case_id=case_id,
                        node_id=str(nid),
                    )
                )
            else:
                if nxt not in nodes:
                    rpt.add(
                        LintFinding(
                            level="error",
                            code="E_NEXT_NOT_FOUND",
                            message=f"choice[{i}].next='{nxt}' 不在 nodes 裡",
                            case_id=case_id,
                            node_id=str(nid),
                        )
                    )

    # recommended quit node
    if "quit" not in nodes:
        rpt.add(
            LintFinding(
                level="warn",
                code="W_QUIT_MISSING",
                message="建議提供 quit 節點（統一 end screen）",
                case_id=case_id,
            )
        )
    else:
        q = nodes.get("quit") or {}
        if isinstance(q, dict):
            for k in ("can_quit", "can_replay"):
                if k in q and not isinstance(q.get(k), bool):
                    rpt.add(
                        LintFinding(
                            level="warn",
                            code="W_QUIT_FLAG_TYPE",
                            message=f"quit.{k} 建議為 bool",
                            case_id=case_id,
                            node_id="quit",
                        )
                    )

    # solve_rule references
    _lint_solve_rule_refs(rpt, case_id, nodes, solve_rule)

    # unreachable nodes (only if start exists)
    if start and start in nodes:
        reachable = _walk_reachable(nodes, start)
        for nid in nodes.keys():
            if nid not in reachable:
                rpt.add(
                    LintFinding(
                        level="warn",
                        code="W_NODE_UNREACHABLE",
                        message="節點不可達（從 start 走不到）",
                        case_id=case_id,
                        node_id=str(nid),
                    )
                )

    return rpt


def _walk_reachable(nodes: Dict[str, Any], start: str) -> Set[str]:
    seen: Set[str] = set()
    stack: List[str] = [start]
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)

        node = nodes.get(nid)
        if not isinstance(node, dict):
            continue

        for c in _iter_choice_dicts(node):
            nxt = _norm_id(c.get("next") or "")
            if nxt and nxt in nodes and nxt not in seen:
                stack.append(nxt)

    return seen


def _lint_solve_rule_refs(
    rpt: LintReport, case_id: str, nodes: Dict[str, Any], solve_rule: Dict[str, Any]
) -> None:
    def check_node_key(key: str, required: bool = False) -> None:
        v = _norm_id(solve_rule.get(key) or "")
        if required and not v:
            rpt.add(
                LintFinding(
                    level="warn",
                    code="W_SOLVE_RULE_EMPTY",
                    message=f"solve_rule.{key} 為空（若此案不用可忽略）",
                    case_id=case_id,
                )
            )
            return
        if v and v not in nodes:
            rpt.add(
                LintFinding(
                    level="error",
                    code="E_SOLVE_RULE_NODE_NOT_FOUND",
                    message=f"solve_rule.{key}='{v}' 不在 nodes 裡",
                    case_id=case_id,
                )
            )

    check_node_key("accuse_node", required=True)

    # old flow
    check_node_key("ending_check_node", required=False)
    check_node_key("ending_wrong_node", required=False)
    check_node_key("reason_node", required=False)
    check_node_key("end_screen_node", required=False)

    # version S tri endings
    check_node_key("ending_clear_node", required=False)
    check_node_key("ending_nudge_node", required=False)
    check_node_key("ending_defer_node", required=False)

    # mapping sanity: accuse_choice_to_suspect
    mapping = solve_rule.get("accuse_choice_to_suspect")
    accuse_node = _norm_id(solve_rule.get("accuse_node") or "")
    if mapping is None:
        return
    if not isinstance(mapping, dict):
        rpt.add(
            LintFinding(
                level="warn",
                code="W_ACC_MAPPING_TYPE",
                message="solve_rule.accuse_choice_to_suspect 建議為 dict",
                case_id=case_id,
            )
        )
        return
    if accuse_node and accuse_node in nodes:
        node = nodes.get(accuse_node) or {}
        if isinstance(node, dict):
            choice_count = len(_iter_choice_dicts(node))
            for k in mapping.keys():
                try:
                    ki = int(str(k))
                except Exception:
                    rpt.add(
                        LintFinding(
                            level="warn",
                            code="W_ACC_MAPPING_KEY",
                            message=f"accuse_choice_to_suspect key='{k}' 不是數字字串",
                            case_id=case_id,
                        )
                    )
                    continue
                if ki <= 0 or ki > choice_count:
                    rpt.add(
                        LintFinding(
                            level="warn",
                            code="W_ACC_MAPPING_RANGE",
                            message=f"accuse_choice_to_suspect key='{k}' 超出 accuse choices 範圍 (1..{choice_count})",
                            case_id=case_id,
                        )
                    )


def lint_cases(cases: Dict[str, Any]) -> LintReport:
    """Lint all cases; 合併成一份總報告。"""
    rpt = LintReport()
    if not isinstance(cases, dict):
        rpt.add(
            LintFinding(
                level="error",
                code="E_CASES_NOT_DICT",
                message="CASES 必須是 dict",
            )
        )
        return rpt

    for cid, c in cases.items():
        if not isinstance(c, dict):
            rpt.add(
                LintFinding(
                    level="error",
                    code="E_CASE_NOT_DICT",
                    message="case 必須是 dict",
                    case_id=str(cid),
                )
            )
            continue

        title = (c.get("title") or "").strip()
        start = (c.get("start") or "").strip()
        nodes = c.get("nodes")
        solve_rule = c.get("solve_rule") or {}

        cr = lint_story_nodes(
            case_id=str(cid),
            title=title,
            nodes=nodes if isinstance(nodes, dict) else {},
            start=start,
            solve_rule=solve_rule if isinstance(solve_rule, dict) else {},
        )
        rpt.errors.extend(cr.errors)
        rpt.warnings.extend(cr.warnings)

    return rpt


def _print_report(rpt: LintReport) -> None:
    txt = rpt.to_text()
    if txt:
        print(txt)
    else:
        print("✅ story_lint: OK")


def _load_cases_best_effort() -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        from questforge.content.cases import CASES  # type: ignore

        return CASES, "questforge.content.cases"
    except Exception as e:
        return None, f"failed_import_cases: {type(e).__name__} {e!r}"


def main() -> int:
    cases, src = _load_cases_best_effort()
    if cases is None:
        print(f"❌ story_lint: {src}")
        return 2

    rpt = lint_cases(cases)
    _print_report(rpt)
    return 0 if rpt.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
