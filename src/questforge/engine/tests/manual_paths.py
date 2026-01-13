# src/questforge/engine/tests/manual_paths.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from questforge.content.cases import CASES
from questforge.core.models import DetectiveState, GameConfig
from questforge.engine.actions import PlayerAction
from questforge.engine.session import GameSession


# ------------------------------------------------------------
# Data structures
# ------------------------------------------------------------
@dataclass(frozen=True)
class CheckPoint:
    """每個 checkpoint 都是可對照輸出的固定資料。"""

    label: str
    node: str
    last_reason_ids: List[str]
    last_reason_text: str
    commands: List[str]


@dataclass(frozen=True)
class StepSpec:
    """一步：對 session 做某個動作，回傳 StepResult（或 None）。"""

    label: str
    act: Callable[[GameSession], Any]  # usually returns StepResult


@dataclass(frozen=True)
class ManualPath:
    name: str
    case_id: str
    setup: Callable[[GameSession], None]
    steps: Sequence[StepSpec]
    asserts: Callable[[List[CheckPoint], GameSession], None]


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def _cmd_types(res) -> List[str]:
    out: List[str] = []
    for c in getattr(res, "commands", None) or []:
        t = (c.get("type") or "").strip()
        if t:
            out.append(t)
    return out


def _snapshot(label: str, session: GameSession, res) -> CheckPoint:
    return CheckPoint(
        label=label,
        node=(session.current or "").strip(),
        last_reason_ids=list(session.state.last_reason_ids or []),
        last_reason_text=(session.state.last_reason_text or "").strip(),
        commands=_cmd_types(res),
    )


def _print_cp(cp: CheckPoint) -> None:
    print("\n" + "=" * 60)
    print(f"[{cp.label}]")
    print(f"node: {cp.node}")
    print(f"last_reason_ids: {cp.last_reason_ids}")
    print(f"last_reason_text: {cp.last_reason_text!r}")
    print(f"commands: {cp.commands}")
    print("=" * 60)


def _new_session(case_id: str, *, config: Optional[GameConfig] = None) -> GameSession:
    config = config or GameConfig()
    case = CASES[case_id]
    return GameSession(
        state=DetectiveState(),
        nodes=case["nodes"],
        start_node=case["start"],
        config=config,
        solve_rule=case.get("solve_rule", {}) or {},
    )


def _step_choose(i: int) -> Callable[[GameSession], Any]:
    return lambda s: s.step(PlayerAction(type="choose", choice_index=i))


def _step_set_reasons(
    *, ids: List[str], text: str = ""
) -> Callable[[GameSession], Any]:
    return lambda s: s.step(
        PlayerAction(type="set_reasons", reason_ids=ids, reason_text=text)
    )


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


# ------------------------------------------------------------
# Day18-D3: validate case configs (early fail)
# ------------------------------------------------------------
def validate_case_configs(*, only_case_ids: Optional[List[str]] = None) -> None:
    """
    掃 CASES 的 solve_rule 重要欄位，提前抓錯，避免跑到一半才卡住。
    """
    ids = list(CASES.keys())
    if only_case_ids:
        allow = set([x.strip() for x in only_case_ids if x and x.strip()])
        ids = [x for x in ids if x in allow]

    problems: List[str] = []

    for cid in ids:
        case = CASES.get(cid) or {}
        nodes = case.get("nodes") or {}
        solve = case.get("solve_rule") or {}

        if not isinstance(solve, dict):
            problems.append(f"case {cid}: solve_rule must be dict")
            continue

        accuse_node = str(solve.get("accuse_node") or "").strip()
        reason_node = str(solve.get("reason_node") or "").strip()
        ending_node = str(solve.get("ending_check_node") or "ending_check").strip()

        if accuse_node and accuse_node not in nodes:
            problems.append(
                f"case {cid}: accuse_node '{accuse_node}' not found in nodes"
            )
        if reason_node and reason_node not in nodes:
            problems.append(
                f"case {cid}: reason_node '{reason_node}' not found in nodes"
            )
        if ending_node and ending_node not in nodes:
            problems.append(
                f"case {cid}: ending_check_node '{ending_node}' not found in nodes"
            )

        # reason_mode optional
        mode = str(solve.get("reason_mode") or "").strip().lower()
        if mode and mode not in ("choice", "text", "voice"):
            problems.append(
                f"case {cid}: reason_mode '{mode}' invalid (choice/text/voice)"
            )

        # reason_options format
        opts = solve.get("reason_options")
        if opts is not None and not isinstance(opts, list):
            problems.append(f"case {cid}: reason_options must be list if provided")
        if isinstance(opts, list):
            for i, o in enumerate(opts):
                if not isinstance(o, dict):
                    problems.append(f"case {cid}: reason_options[{i}] must be dict")
                    continue
                oid = str(o.get("id") or "").strip()
                txt = str(o.get("text") or "").strip()
                if not oid:
                    problems.append(f"case {cid}: reason_options[{i}] missing 'id'")
                if not txt:
                    problems.append(f"case {cid}: reason_options[{i}] missing 'text'")

    if problems:
        raise AssertionError(
            "Case config validation failed:\n- " + "\n- ".join(problems)
        )


# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------
def build_paths() -> List[ManualPath]:
    paths: List[ManualPath] = []

    # Path2: 不確定路線：進理由但沒填 -> 回 accuse -> 選不確定 -> ending_check
    def setup_p2(s: GameSession) -> None:
        s.current = "final_accuse"

    def asserts_p2(cps: List[CheckPoint], s: GameSession) -> None:
        cp0 = cps[0]
        _assert(
            cp0.node == "accuse_reason",
            "P2: expected node accuse_reason after entering reason",
        )
        _assert(
            "ask_reason" in cp0.commands,
            "P2: expected ask_reason command at accuse_reason",
        )

        cp1 = cps[1]
        _assert(
            cp1.node == (s._accuse_node() or "accuse"),
            "P2: expected back to accuse after empty reasons",
        )
        _assert(cp1.last_reason_ids == [], "P2: expected last_reason_ids empty")
        _assert(cp1.last_reason_text == "", "P2: expected last_reason_text empty")

        cp2 = cps[2]
        _assert(
            cp2.node == (s._ending_check_node() or "ending_check"),
            "P2: expected ending_check after choosing uncertain at accuse",
        )
        _assert(
            "show_reasoning_feedback" in cp2.commands,
            "P2: expected show_reasoning_feedback at ending_check",
        )

    paths.append(
        ManualPath(
            name="path2_uncertain_go_teacher",
            case_id="2",
            setup=setup_p2,
            steps=[
                StepSpec("enter reason (final_accuse choose 4)", _step_choose(4)),
                StepSpec("set_reasons empty", _step_set_reasons(ids=[], text="")),
                StepSpec("choose accuse: 4 (uncertain)", _step_choose(4)),
            ],
            asserts=asserts_p2,
        )
    )

    # Path3: 改理由路線：accuse 頁按「回去改理由」 -> ask_reason -> set_reasons(text) -> 回 accuse
    def setup_p3(s: GameSession) -> None:
        s.state.last_reason_ids = ["mei_took_tape"]
        s.state.last_reason_text = ""
        s.current = s._accuse_node() or "accuse"

    def act_choose_edit(s: GameSession):
        view = s.get_view()
        edit_idx = len(view.choices)  # 最後一個是 edit_reasons
        return s.step(PlayerAction(type="choose", choice_index=edit_idx))

    def asserts_p3(cps: List[CheckPoint], s: GameSession) -> None:
        cp0 = cps[0]
        _assert(
            cp0.node == (s._reason_node() or "accuse_reason"),
            "P3: expected reason_node after edit_reasons",
        )
        _assert(
            "ask_reason" in cp0.commands, "P3: expected ask_reason after edit_reasons"
        )
        _assert(
            cp0.last_reason_ids == ["mei_took_tape"],
            "P3: before reselect, old reason_ids should still exist",
        )

        cp1 = cps[1]
        _assert(
            cp1.node == (s._accuse_node() or "accuse"),
            "P3: expected back to accuse after set_reasons(text)",
        )
        _assert(
            cp1.last_reason_ids == [], "P3: expected reason_ids cleared in text-mode"
        )
        _assert(
            cp1.last_reason_text == "我看到東東一直抱得很緊",
            "P3: expected reason_text stored",
        )

    paths.append(
        ManualPath(
            name="path3_edit_reason_from_accuse",
            case_id="2",
            setup=setup_p3,
            steps=[
                StepSpec("choose edit_reasons", act_choose_edit),
                StepSpec(
                    "set_reasons(text)",
                    _step_set_reasons(ids=[], text="我看到東東一直抱得很緊"),
                ),
            ],
            asserts=asserts_p3,
        )
    )

    # Path4: text-mode 理由 -> 回 accuse 後，reason_text 必須仍在
    def setup_p4(s: GameSession) -> None:
        s.current = s._reason_node() or "accuse_reason"

    def asserts_p4(cps: List[CheckPoint], s: GameSession) -> None:
        cp0 = cps[0]
        _assert(
            cp0.node == (s._accuse_node() or "accuse"),
            "P4: expected back to accuse after set_reasons(text)",
        )
        _assert(
            cp0.last_reason_ids == [], "P4: expected reason_ids cleared in text-mode"
        )
        _assert(
            cp0.last_reason_text == "我看到東東一直抱得很緊",
            "P4: expected reason_text stored (must not be cleared)",
        )

        cp1 = cps[1]
        _assert(
            cp1.last_reason_text == "我看到東東一直抱得很緊",
            "P4: reason_text must remain after choosing in accuse (no auto-clear)",
        )

    paths.append(
        ManualPath(
            name="path4_text_reason_persists_on_accuse",
            case_id="2",
            setup=setup_p4,
            steps=[
                StepSpec(
                    "set_reasons(text) at reason_node",
                    _step_set_reasons(ids=[], text="我看到東東一直抱得很緊"),
                ),
                StepSpec("choose accuse: 4 (uncertain)", _step_choose(4)),
            ],
            asserts=asserts_p4,
        )
    )

    # 仍應 gate 到 reason_node，並讓 ask_reason 退化成 text-mode，最後可用 set_reasons(text) 回 accuse
    def setup_p5(s: GameSession) -> None:
        # 模擬案件漏配：reason_options 清空，但 reason_mode 仍是 choice
        s.solve_rule = dict(s.solve_rule or {})
        s.solve_rule["reason_mode"] = "choice"
        s.solve_rule["reason_options"] = []  # 缺失

        # 建立一個臨時節點：選 1 會跳到 accuse_node
        accuse = (s._accuse_node() or "accuse").strip()
        s.nodes["__tmp_to_accuse__"] = {
            "title": "tmp",
            "narration": "tmp",
            "tag": "investigate",
            "choices": [
                {"text": "go accuse", "next": accuse},
            ],
        }
        s.current = "__tmp_to_accuse__"

        # 確保目前沒有理由
        s.state.last_reason_ids = []
        s.state.last_reason_text = ""
        s.state.last_accuse = ""

    def asserts_p5(cps: List[CheckPoint], s: GameSession) -> None:
        # cp0: choose tmp -> 應被 gate 到 reason_node 且帶 ask_reason
        cp0 = cps[0]
        _assert(
            cp0.node == (s._reason_node() or "accuse_reason"),
            "P5: expected gate to reason_node",
        )
        _assert(
            "ask_reason" in cp0.commands,
            "P5: expected ask_reason command at reason_node (fallback to text)",
        )

        # cp1: set_reasons(text) -> 回 accuse，且 reason_text 存下來
        cp1 = cps[1]
        _assert(
            cp1.node == (s._accuse_node() or "accuse"),
            "P5: expected back to accuse after set_reasons(text)",
        )
        _assert(
            cp1.last_reason_text == "我看到桌上有東西被拉過",
            "P5: expected reason_text stored in fallback text-mode",
        )

    paths.append(
        ManualPath(
            name="path5_choice_mode_missing_options_fallback_text",
            case_id="2",
            setup=setup_p5,
            steps=[
                StepSpec(
                    "choose tmp_to_accuse (should gate to reason)", _step_choose(1)
                ),
                StepSpec(
                    "set_reasons(text) fallback",
                    _step_set_reasons(ids=[], text="我看到桌上有東西被拉過"),
                ),
            ],
            asserts=asserts_p5,
        )
    )

    return paths


# ------------------------------------------------------------
# Runner
# ------------------------------------------------------------
def run_path(
    path: ManualPath, *, verbose: bool = True, return_checkpoints: bool = False
):
    session = _new_session(path.case_id)
    path.setup(session)

    cps: List[CheckPoint] = []

    if verbose:
        print(f"\n### ManualPath: {path.name} ###")

    for st in path.steps:
        res = st.act(session)
        _assert(res is not None, f"{path.name}: step '{st.label}' returned None")
        cp = _snapshot(st.label, session, res)
        cps.append(cp)
        if verbose:
            _print_cp(cp)

    path.asserts(cps, session)

    if verbose:
        print(f"\n✅ {path.name} OK")

    if return_checkpoints:
        return cps
    return None


def run_all(
    *,
    only: Optional[List[str]] = None,
    verbose: bool = True,
    validate_cases: bool = True,
) -> None:
    if validate_cases:
        validate_case_configs()

    paths = build_paths()
    if only:
        allow = set([x.strip() for x in only if x and x.strip()])
        paths = [p for p in paths if p.name in allow]

    if not paths:
        print("No paths matched.")
        return

    ok = 0
    failed: List[Tuple[str, str]] = []

    for p in paths:
        try:
            run_path(p, verbose=verbose)
            ok += 1
        except Exception as e:
            failed.append((p.name, str(e)))
            print(f"\n❌ {p.name} FAILED: {e}")

    print("\n" + "-" * 60)
    print(f"Result: {ok}/{len(paths)} passed")
    if failed:
        print("Failed:")
        for name, err in failed:
            print(f" - {name}: {err}")
    print("-" * 60)
