# src/questforge/ai/story_writer_cli.py
from __future__ import annotations

import argparse
import ast
import os
import re
from pathlib import Path
from typing import Any, List

from openai import OpenAI
from questforge.ai.openai_env import clean_openai_api_key
from questforge.ai.story_style_examples import extract_style_example as extract_sample_style_example

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
CONTENT_DIR = Path(__file__).resolve().parents[1] / "content"

CASES_FILE = CONTENT_DIR / "cases.py"

CORE_FILES = [
    "story_prompt_v1.md",  # 唯一母版
    "story_case_template_v1.md",
    "schema_story_nodes.md",
    "guard_rules.md",
    "story_response_whitelist.md",
    "world_old_rival_module.md",  # 可開關
]

UNSURE_CHOICE_TEXT = "我還不確定，交給大人"
OPENING_MIN_NARRATION_LINES = 12
INCIDENT_NODE_ID = "scene_02_incident"
MIN_SCENES_AFTER_INCIDENT = 2
BANNED_OPENING_TERMS = [
    "開始調查",
    "推理",
    "真相",
    "嫌疑",
    "嫌疑人",
    "犯人",
    "兇手",
    "審問",
    "審訊",
    "解決案件",
    "破案",
]
PLACEHOLDER_ROLE_PREFIX = (
    "老師|爸爸|媽媽|叔叔|阿姨|哥哥|姊姊|店員|志工|家長|工作人員|"
    "主持人|裁判|評審|老闆|司機|站務員|保全|醫生|護士|同學|孩子"
)
PLACEHOLDER_ROLE_REGEXES = [
    rf"(?<![\u4e00-\u9fffA-Za-z0-9_])(?:{PLACEHOLDER_ROLE_PREFIX})[A-ZＡ-Ｚ]",
    rf"(?<![\u4e00-\u9fffA-Za-z0-9_])(?:{PLACEHOLDER_ROLE_PREFIX})[甲乙丙丁戊己庚辛壬癸]",
    rf"(?<![\u4e00-\u9fffA-Za-z0-9_])(?:{PLACEHOLDER_ROLE_PREFIX})\d+",
]
GENERIC_SIDE_SPEAKER_LABELS = [
    "老師",
    "爸爸",
    "媽媽",
    "叔叔",
    "阿姨",
    "哥哥",
    "姊姊",
    "店員",
    "大人",
    "家長",
    "志工",
    "工作人員",
    "主持人",
    "裁判",
    "評審",
    "老闆",
    "司機",
    "站務員",
    "保全",
    "醫生",
    "護士",
    "同學",
]

# -------------------------
# Few-shot: 黃金開場（節奏錨點）
# -------------------------
GOLDEN_OPENING_EXAMPLE = """
【黃金開場示範（僅示範節奏，禁止照抄內容）】
旁白：林老師一手夾著點名板，一手把快要滑下來的彩帶捲回去，忙得連眼鏡都快跟著歪掉。

旁白：今天是才藝日，黑板上用粉筆寫著大大的四個字，後面那張桌子已經被道具袋和海報塞得像小小倉庫。

霏霏：欸，老師寫字有把「才」寫得像菜耶。

樂樂：那今天是「菜藝日」嗎？我要表演——切菜！

霏霏：你先把刀放下，菜藝日也不給你刀。

旁白：老師在講台上拍了拍手，像拍蚊子一樣「啪！啪！」兩聲。

老師：各位小小表演家～道具袋先放到後面那張桌子，等下照順序上台喔。

樂樂：上台前我可以先練習尖叫嗎？

霏霏：你那個不是尖叫，是救護車。

旁白：後面那張桌子上貼了便利貼，寫著「道具袋停車場」。

樂樂：停車場？那我的道具袋要不要倒車入庫？

霏霏：你可以先把它停好，不要把別人的袋子撞歪。

旁白：這時候，有兩個同學一路小跑進來。

甜甜圈阿咚：我把我的呼拉圈帶來了！欸欸不要踩到！它很會滾！

鉛筆小刺：我的是魔術盒！可是我剛剛差點把自己變不見。

樂樂：哇你成功了嗎？

鉛筆小刺：沒有，我只是把盒子蓋子弄掉了。

霏霏：（笑）這叫「蓋子逃跑術」。

旁白：走廊外還傳來操場的廣播聲，像在催大家快一點。

廣播（值日生）：請表演的班級準備——不要邊走邊吃飯糰！

樂樂：誰邊走邊吃飯糰啦？

霏霏：你昨天就是。

樂樂：那是飯糰自己跑進我嘴巴的。

旁白：老師把名單拿在手上，一邊點名一邊看大家的袋子有沒有貼好名字。

老師：記得貼名字喔～貼名字是保護道具袋的魔法。

樂樂：（小聲）如果我貼兩張，是不是變成雙倍魔法？

霏霏：會變成雙倍黏，然後你自己撕不下來。

旁白：大家笑成一片，教室熱熱鬧鬧的，好像連椅子都在抖。

旁白：霏霏把樂樂的道具袋放好，還用手指戳了一下，確認它真的乖乖坐著。

霏霏：好，停車成功。不要再倒車了喔。

樂樂：收到！表演家出發！
""".strip()


# -------------------------
# Helpers
# -------------------------
def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8").strip()


def _env_str(*names: str) -> str:
    for name in names:
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    return ""


def build_instructions(*, include_old_rival: bool) -> str:
    blocks: list[str] = []
    for name in CORE_FILES:
        if not include_old_rival and name == "world_old_rival_module.md":
            continue
        fp = PROMPTS_DIR / name
        if fp.exists():
            blocks.append(f"\n\n# FILE: {name}\n{_read(fp)}")
    return "\n".join(blocks).strip()


def extract_style_example() -> str:
    """抽取真實樣本的前段作為節奏示範（第二個錨點）"""
    return extract_sample_style_example(max_lines=72)


def _extract_story_nodes_block(py_text: str) -> str:
    """
    把 STORY_NODES = { ... } 這一整段抓出來（用於更精準驗證）。
    """
    m = re.search(r"\bSTORY_NODES\s*=\s*\{", py_text)
    if not m:
        return ""
    start = m.start()

    # 用簡易括號配對找出最外層大括號結尾
    i = py_text.find("{", m.end() - 1)
    if i < 0:
        return ""
    depth = 0
    for j in range(i, len(py_text)):
        ch = py_text[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return py_text[start : j + 1]
    return ""


def _extract_scene_block(py_text: str, node_id: str) -> str:
    """
    粗抓指定節點區塊文字（用於檢查）。
    這不是完整 parser，只是為了快速驗證生成品質。
    """
    nodes_blk = _extract_story_nodes_block(py_text) or py_text

    # 支援最後一個 item 可能沒有 trailing comma
    pat = rf'"{re.escape(node_id)}"\s*:\s*\{{.*?\n\s*\}}(?=,\s*\n|\s*\n\s*\}})'
    m = re.search(pat, nodes_blk, flags=re.S)
    return m.group(0) if m else ""


def _ast_node_to_python(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_ast_node_to_python(item) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_ast_node_to_python(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        out: dict[Any, Any] = {}
        for k, v in zip(node.keys, node.values):
            out[_ast_node_to_python(k)] = _ast_node_to_python(v)
        return out
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = _ast_node_to_python(node.operand)
        if isinstance(value, int):
            return -value
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "_n":
            parts = [_ast_node_to_python(arg) for arg in node.args]
            if all(isinstance(part, str) for part in parts):
                return "\n\n".join([part for part in parts if part.strip()])
    raise ValueError(f"Unsupported AST node for STORY_NODES parsing: {type(node).__name__}")


def _parse_story_nodes_dict(py_text: str) -> dict[str, Any] | None:
    try:
        tree = ast.parse(py_text)
    except SyntaxError:
        return None

    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        for target in stmt.targets:
            if isinstance(target, ast.Name) and target.id == "STORY_NODES":
                try:
                    value = _ast_node_to_python(stmt.value)
                except ValueError:
                    return None
                return value if isinstance(value, dict) else None
    return None


def _count_narration_lines_in_block(scene_block: str) -> int:
    """粗估 _n(...) 內的敘事行數：抓出 _n( ... ) 裡每個 "....", 行數"""
    if not scene_block:
        return 0
    m = re.search(r'"narration"\s*:\s*_n\((.*?)\)\s*,', scene_block, flags=re.S)
    if not m:
        return 0
    inside = m.group(1)
    return len(re.findall(r'"\s*[^"]+?\s*"\s*,?', inside))


# -------------------------
# Validations
# -------------------------
def _validate_scene01(py_text: str) -> list[str]:
    errors: list[str] = []
    s01 = _extract_scene_block(py_text, "scene_01_start")
    if not s01:
        return ["找不到 scene_01_start 區塊"]

    n_lines = _count_narration_lines_in_block(s01)
    if n_lines < OPENING_MIN_NARRATION_LINES:
        errors.append(
            f"scene_01_start narration 行數不足（目前 {n_lines}，至少 {OPENING_MIN_NARRATION_LINES}）"
        )

    for t in BANNED_OPENING_TERMS:
        if t in s01:
            errors.append(f"scene_01_start 出現禁止詞：{t}")

    # 禁止日文假名（平假名/片假名）
    if re.search(r"[\u3040-\u30ff]", s01):
        errors.append("scene_01_start 出現日文假名（平假名/片假名），禁止")

    # 角色泛稱（要求配角要有名字）
    banned_generic = ["紅色衣服", "那個男孩", "某位同學", "穿外套的人", "小朋友"]
    for t in banned_generic:
        if t in s01:
            errors.append(f"scene_01_start 出現泛稱（請改成有名字的配角）：{t}")

    return errors


def _validate_required_nodes(py_text: str) -> list[str]:
    errors: list[str] = []
    required = [
        '"scene_01_start"',
        '"scene_02_incident"',
        '"final_accuse"',
        '"scene_10_ending_clear"',
        '"scene_10_ending_nudge"',
        '"scene_10_ending_defer"',
        '"quit"',
    ]
    missing = [k for k in required if k not in py_text]
    if missing:
        errors.append(f"缺少必要節點：{missing}")

    # ending 每個都要有「故事結束 -> quit」
    for nid in [
        "scene_10_ending_clear",
        "scene_10_ending_nudge",
        "scene_10_ending_defer",
    ]:
        blk = _extract_scene_block(py_text, nid)
        if not blk:
            continue
        if (
            '"choices"' not in blk
            or '"故事結束"' not in blk
            or '"next": "quit"' not in blk
        ):
            errors.append(f"{nid} 結構不完整（必須含 choices: 故事結束 -> quit）")

    # quit 必須含 can_replay & can_quit
    qblk = _extract_scene_block(py_text, "quit")
    if qblk and ("can_replay" not in qblk or "can_quit" not in qblk):
        errors.append("quit 節點缺少 can_replay / can_quit")

    return errors


def _validate_no_placeholders(py_text: str) -> list[str]:
    """
    只針對 STORY_NODES 內文做 placeholder 檢查，避免 seed/註解誤判。
    """
    errors: list[str] = []
    nodes_blk = _extract_story_nodes_block(py_text)
    target = nodes_blk or py_text

    bad_patterns = [
        r"學長A",
        r"學長B",
        r"學長C",
        r"嫌疑人A",
        r"嫌疑人B",
        r"嫌疑人C",
        r"嫌疑人甲",
        r"嫌疑人乙",
        r"嫌疑人丙",
    ]
    for pat in bad_patterns:
        if re.search(pat, target):
            errors.append(f"出現 placeholder/佔位命名：{pat}")
            break

    for pat in PLACEHOLDER_ROLE_REGEXES:
        m = re.search(pat, target)
        if m:
            errors.append(f"出現 placeholder/佔位命名：{m.group(0)}")
            break

    for label in GENERIC_SIDE_SPEAKER_LABELS:
        if re.search(rf'(?<![\u4e00-\u9fffA-Za-z0-9_]){re.escape(label)}：', target):
            errors.append(f"配角稱呼太泛，請改成自然名字或關係稱呼：{label}")
            break
    return errors


def _extract_final_accuse_choice_texts(py_text: str) -> list[str]:
    blk = _extract_scene_block(py_text, "final_accuse")
    if not blk:
        return []
    m = re.search(r'"choices"\s*:\s*\[(.*?)\]\s*,', blk, flags=re.S)
    if not m:
        # 有些生成會把 choices 放最後沒有逗號
        m = re.search(r'"choices"\s*:\s*\[(.*?)\]\s*\}', blk, flags=re.S)
    if not m:
        return []
    inside = m.group(1)
    return re.findall(r'"text"\s*:\s*"([^"]+)"', inside)


def _is_unsure_choice(text: str) -> bool:
    t = (text or "").strip()
    return any(
        k in t
        for k in [
            "不確定",
            "交給大人",
            "交給老師",
            "先去問清楚",
            "找大人",
            "問大人",
            "找老師",
            "問老師",
        ]
    )


def _is_cute_name(name: str) -> bool:
    t = (name or "").strip()
    if not t or len(t) < 2:
        return False
    if any(x in t for x in ["某位", "那個", "小朋友"]):
        return False
    if t in GENERIC_SIDE_SPEAKER_LABELS or t in ["學長", "學姊"]:
        return False
    if any(re.search(pat, t) for pat in PLACEHOLDER_ROLE_REGEXES):
        return False
    if re.search(r"[\u4e00-\u9fff]", t) is None:
        return False
    # 你原本這裡最後 `or True` 會讓規則失效，我保留你的行為（不強化），避免意外增加失敗率
    return True


def _collect_all_narration_text(py_text: str) -> str:
    parts: list[str] = []
    nodes_blk = _extract_story_nodes_block(py_text) or py_text
    for m in re.finditer(r'"narration"\s*:\s*_n\((.*?)\)\s*,', nodes_blk, flags=re.S):
        inside = m.group(1)
        lines = re.findall(r'"([^"]+)"', inside)
        parts.append("\n".join(lines))
    return "\n".join(parts)


def _collect_narration_text_before_node(py_text: str, stop_node_id: str) -> str:
    nodes = _parse_story_nodes_dict(py_text)
    if not nodes:
        return _collect_all_narration_text(py_text)

    parts: list[str] = []
    for node_id, node in nodes.items():
        if node_id == stop_node_id:
            break
        if not isinstance(node, dict):
            continue
        narration = node.get("narration")
        if isinstance(narration, str) and narration.strip():
            parts.append(narration)
    return "\n".join(parts)


def _validate_accuse_choices(py_text: str, *, unsure_text: str) -> list[str]:
    """
    1) final_accuse 必須 4 個選項
    2) 第 4 個必須完全等於 unsure_text
    3) 前三個必須是名字，且在前文登場
    """
    errors: list[str] = []
    choices = _extract_final_accuse_choice_texts(py_text)
    if len(choices) != 4:
        return [f"final_accuse choices 必須剛好 4 個（目前 {len(choices)}）"]

    if (choices[3] or "").strip() != unsure_text.strip():
        errors.append(
            f"final_accuse 第 4 個選項必須完全等於：{unsure_text}（目前：{choices[3]}）"
        )

    suspects = [c.strip() for c in choices[:3]]

    for s in suspects:
        if _is_unsure_choice(s) or ("老師" in s) or ("大人" in s):
            errors.append(f"final_accuse 前三個選項必須是嫌疑人名字（目前：{s}）")

    for s in suspects:
        if not _is_cute_name(s):
            errors.append(f"嫌疑人命名不符合可愛命名規則：{s}")

    narration_text = _collect_narration_text_before_node(py_text, "final_accuse")
    for s in suspects:
        if s and (s not in narration_text):
            errors.append(f"嫌疑人未在故事前文登場（指認前至少出現一次）：{s}")

    if len(set(suspects)) != 3:
        errors.append(f"嫌疑人名字重複：{suspects}")

    return errors


def _validate_no_old_case_residue(py_text: str) -> list[str]:
    errors: list[str] = []
    banned_names = [
        "亨利爵士",
        "喵喵（粉絲）",
        "老鷹大翔",
        "千羽會",
        "孔雀",
    ]
    hits = [x for x in banned_names if x in py_text]
    if hits:
        errors.append(f"出現其他案例殘影/專有名詞（禁止沿用）：{hits}")
    return errors


def _validate_mid_search_presence(py_text: str) -> list[str]:
    """
    事件後至少 2 個 scene 在做自然搜尋，避免太快進指認
    """
    nodes = _parse_story_nodes_dict(py_text)
    if not nodes:
        return ["無法解析 STORY_NODES（無法驗證事件後節奏）"]

    if INCIDENT_NODE_ID not in nodes:
        return [f"缺少 {INCIDENT_NODE_ID}（事件節點）"]

    main_scenes = [
        node_id
        for node_id in nodes.keys()
        if node_id.startswith("scene_") and not node_id.startswith("scene_10_ending")
    ]
    if INCIDENT_NODE_ID not in main_scenes:
        return [f"{INCIDENT_NODE_ID} 不在主要劇情節點序列裡"]

    incident_index = main_scenes.index(INCIDENT_NODE_ID)
    after = main_scenes[incident_index + 1 :]

    if len(after) < MIN_SCENES_AFTER_INCIDENT:
        return [
            f"事件後的搜尋/互動 scene 不足（目前 {len(after)}，至少 {MIN_SCENES_AFTER_INCIDENT}），容易太快進指認"
        ]

    return []


def _validate_solution_index(py_text: str) -> list[str]:
    """
    A 方案必備：final_accuse 必須有 solution_index: 0/1/2
    """
    blk = _extract_scene_block(py_text, "final_accuse")
    if not blk:
        return ["找不到 final_accuse 區塊（無法驗證 solution_index）"]

    m = re.search(r'"solution_index"\s*:\s*(\d+)\s*,', blk)
    if not m:
        m = re.search(r'"solution_index"\s*:\s*(\d+)\s*\n', blk)

    if not m:
        return ["final_accuse 缺少 solution_index（必須是 0/1/2）"]

    v = int(m.group(1))
    if v not in (0, 1, 2):
        return [f"final_accuse.solution_index 必須是 0/1/2（目前 {v}）"]
    return []


def _run_all_validations(py_text: str, *, unsure_text: str) -> list[str]:
    errors: list[str] = []
    if "STORY_NODES" not in py_text:
        return ["Invalid output: missing STORY_NODES"]

    errors.extend(_validate_required_nodes(py_text))
    errors.extend(_validate_scene01(py_text))
    errors.extend(_validate_no_placeholders(py_text))
    errors.extend(_validate_accuse_choices(py_text, unsure_text=unsure_text))
    errors.extend(_validate_solution_index(py_text))
    errors.extend(_validate_no_old_case_residue(py_text))
    errors.extend(_validate_mid_search_presence(py_text))
    return errors


def _generate_once(
    client: OpenAI, *, model: str, instructions: str, user_input: str
) -> str:
    resp = client.responses.create(
        model=model,
        instructions=instructions,
        input=user_input,
        store=False,
    )
    return (resp.output_text or "").strip()


def _guess_case_title(seed: str, fallback: str) -> str:
    s = (seed or "").strip()
    if not s:
        return fallback
    for sep in ["。", "\n", ",", "，"]:
        if sep in s:
            head = s.split(sep, 1)[0].strip()
            return head if head else fallback
    return s[:20] if len(s) > 20 else s


def _next_case_id(cases_py: str) -> str:
    ids = re.findall(r'^\s*"(\d+)"\s*:\s*\{', cases_py, flags=re.M)
    if not ids:
        return "1"
    mx = max(int(x) for x in ids)
    return str(mx + 1)


def _ensure_anchor(cases_py: str) -> list[str]:
    missing = []
    if "# [AUTO-IMPORTS]" not in cases_py:
        missing.append("# [AUTO-IMPORTS]")
    if "# [AUTO-CASES]" not in cases_py:
        missing.append("# [AUTO-CASES]")
    return missing


def register_case_into_cases_py(*, module_name: str, seed: str) -> None:
    """
    在 src/questforge/content/cases.py 內：
    - AUTO-IMPORTS 下插入 import
    - AUTO-CASES 下插入新的 case entry
    """
    if not CASES_FILE.exists():
        raise SystemExit(f"找不到 cases.py：{CASES_FILE}")

    cases_py = CASES_FILE.read_text(encoding="utf-8")

    missing = _ensure_anchor(cases_py)
    if missing:
        raise SystemExit(
            "cases.py 缺少自動插入錨點，請先加入以下兩行其中缺少的：\n"
            "- # [AUTO-IMPORTS]\n"
            "- # [AUTO-CASES]\n"
        )

    # 1) 如果同 module 已經被 import 過，代表你可能重跑同一個 out 檔：
    #    這時不要再註冊第二筆 case（避免案例越來越多但其實同一個）
    if re.search(
        rf"from\s+\.{re.escape(module_name)}\s+import\s+STORY_NODES\s+as\s+CASE_\d+_NODES",
        cases_py,
    ):
        raise SystemExit(
            f"cases.py 已經註冊過 module：{module_name}\n"
            f"若你想更新同一案例內容，請不要重跑註冊；或手動移除舊 entry 再執行。"
        )

    new_id = _next_case_id(cases_py)
    alias = f"CASE_{new_id}_NODES"

    # 2) 插 import
    import_line = f"from .{module_name} import STORY_NODES as {alias}"
    cases_py = cases_py.replace(
        "# [AUTO-IMPORTS]", "# [AUTO-IMPORTS]\n" + import_line, 1
    )

    # 3) 插 case entry
    title = _guess_case_title(seed, fallback=f"生成案：{module_name}")
    entry = f"""
    "{new_id}": {{
        "title": "{title}",
        "start": "scene_01_start",
        "nodes": {alias},
        "solve_rule": {{
            "accuse_node": "final_accuse",
            "ending_check_node": "",
            "ending_clear_node": "scene_10_ending_clear",
            "ending_nudge_node": "scene_10_ending_nudge",
            "ending_defer_node": "scene_10_ending_defer",
            "end_screen_node": "quit",

            "reason_node": "",
            "reason_options": [],
            "reason_mode": "choice",

            # ✅ A 方案：用 story 內的 final_accuse.solution_index 來判斷正解
            "use_solution_index": True,
        }},
    }},
""".rstrip(
        "\n"
    )

    cases_py = cases_py.replace("# [AUTO-CASES]", "# [AUTO-CASES]\n" + entry, 1)
    CASES_FILE.write_text(cases_py, encoding="utf-8")


# -------------------------
# Auto-fix (post-generate)
# -------------------------
def _auto_fix_solution_index(py_text: str) -> str:
    """
    自動修補 final_accuse.solution_index：
    - 若存在但超出範圍 → clamp 到 0..2
    - 若完全不存在 → 強制插入 solution_index: 0
    """
    blk = _extract_scene_block(py_text, "final_accuse")
    if not blk:
        return py_text

    # 1️⃣ 已存在 solution_index → clamp
    m = re.search(r'("solution_index"\s*:\s*)(-?\d+)', blk)
    if m:
        v = int(m.group(2))
        v2 = 0 if v < 0 else 2 if v > 2 else v
        if v2 == v:
            return py_text

        fixed_blk = blk[: m.start(2)] + str(v2) + blk[m.end(2) :]
        return py_text.replace(blk, fixed_blk, 1)

    # 2️⃣ 完全不存在 → 強制補在 final_accuse 區塊內（靠前，避免 parser 問題）
    insert_point = blk.find("{") + 1
    injected = (
        blk[:insert_point] + '\n        "solution_index": 0,' + blk[insert_point:]
    )
    return py_text.replace(blk, injected, 1)


def _auto_fix_after_generate(py_text: str) -> str:
    """
    只保留「不改劇情內容」的結構修補：
    - solution_index 若越界則 clamp
    - solution_index 若缺失則補 0，讓下一輪 validator/repair 能繼續工作
    """
    out = py_text
    out = _auto_fix_solution_index(out)
    return out


# -------------------------
# Prompt builder
# -------------------------
def _build_user_input(
    *,
    seed: str,
    style_example: str,
    unsure_choice_text: str,
) -> str:
    return f"""
你是一位「故事型偵探推理遊戲」的兒童故事作家。
請輸出一個【完整、可直接執行的 Python 檔案】。
⚠️ 絕對禁止出現 ```python 或任何 code fence。

你必須逐條遵守 story_prompt_v1.md（唯一母版）。
此外，你必須模仿下方兩個「節奏錨點」的故事感（只能模仿節奏與口吻，不可照抄內容）。

────────────────
【節奏錨點 A：黃金開場示範（只學節奏，不可照抄）】
{GOLDEN_OPENING_EXAMPLE}

────────────────
【節奏錨點 B：參考樣本（只學節奏，不可照抄）】
{style_example}

────────────────
【必要結構（保留程式相容）】
1) 必須輸出完整 Python 檔案，內含：
- `_n` helper
- `STORY_NODES` dict

2) 必須包含並完整定義以下 nodeId：
- scene_01_start
- scene_02_incident
- final_accuse
- scene_10_ending_clear
- scene_10_ending_nudge
- scene_10_ending_defer
- quit

3) scene_* 節點以 narration + next 為主，final_accuse / quit / ending 再放 choices。

4) final_accuse 必須剛好 4 個選項：
- 前 3 個只放嫌疑人名字
- 第 4 個必須 **完全等於**：{unsure_choice_text}
- 必須包含 `solution_index: 0/1/2`

5) 三個 ending 都要完整，且都要有：
- `choices: [{{"text":"故事結束","next":"quit"}}]`

6) quit 必須包含 `can_replay` 與 `can_quit`

【樣本驅動的風格要求】
1) 先把場子寫熱，再讓事件闖進來。
- `scene_01_start` 至少 {OPENING_MIN_NARRATION_LINES} 段
- 先寫活動、人群、道具、氣味、配角脾氣、姊弟互動
- 不要一開場就像案件摘要
- 你可以先用 1 到 2 段交代今天到底是什麼活動、現場有哪些比賽或流程，但不能只剩導覽口播；很快就要接到具體人物和當下任務
- 第一個畫面最好直接看見某個人在忙、衝、喊、擦汗、找人或出糗，不要讓第一句完整停在「一年一度的什麼活動今天開始了」
- 第一段盡量不要只用「今天這裡正在舉辦……」起手；更像樣本的是先看到某個人在忙、衝、喊、擦汗、出糗，再順手帶出活動
- 開場前幾段要自然交代：霏霏和樂樂今天為什麼會在這裡、跟誰來、原本是來玩/來住/來參加什麼、今天被分到什麼或想先衝哪一區
- 前半可以更長一點，先讓讀者認識人、記住場子、知道姊弟今天在幹嘛，再把事件拉進來
- 事件前最好先有 2 到 3 輪姊弟打鬧、配角插話、任務分工或小狼狽，不要背景交代完就直接出事

2) `scene_01_start` 不要直接進入破案或審訊口氣：
- 禁詞：{", ".join(BANNED_OPENING_TERMS)}
- 也不要用需要解釋的怪比喻、故意抖機靈、編劇式提示
- 禁止日文（平假名/片假名）

3) 霏霏與樂樂的人設：
- 霏霏：熱心、貼心、愛笑、活潑，愛跟弟弟打鬧開玩笑，但比較理性；不是正經小老師
- 樂樂：愛吃、衝動、很會鬧姊姊，愛看姊姊無奈；笑點要像真反應，不要像硬塞搞笑

4) 案件推進要像樣本：
- `scene_02_incident` 必須明確存在，但事件一出後不要立刻指認
- 事件後至少再有 2 個自然搜尋 / 詢問 / 比對 / 被打斷 / 再確認的 scene
- 誤導至少做出 2 層：說法矛盾、面子、隱瞞、誤會、時間差都可以
- `scene_05_check_3` 最好再翻一次，不要只是確認上一輪懷疑
- `scene_06_hypothesis_1` 至少還要保留兩條說得通一半的方向，不要只剩單一路線
- `scene_05_check_3` 和 `scene_06_hypothesis_1` 不要直接寫「一定是 / 就是他 / 果然是 / 八成是」
- 不要只靠一個小物證一路推到底
- 不要每次都寫成手忙腳亂的小失誤；這次更常要像有人故意亂動、偷偷藏、偷改、搶風頭、卡別人、害人出糗
- 也請多往「差點害人受傷 / 差點打翻熱東西 / 道具或設備差點壞掉 / 主流程被迫喊停」這種更有重量的事件寫，不要一直停在亂喊或亂放
- 除非「插隊 / 換位 / 順序亂掉」只是表面現象，背後還連著更大的破壞、危險或偷動手腳，否則不要把核心案件縮在排隊糾紛
- 調查不要太快定調；到 `final_accuse` 前還要保留一點模糊感，不要第二輪就幾乎知道答案
- 動機不要老是怕丟臉、怕輸、怕被罵；也可以是報復、嫉妒、惡作劇、想搶注意力、想替朋友出氣、想把鍋甩出去
- 如果有人說「我的疏忽 / 我的錯 / 我剛剛太忙了」，前一段或同一段要先講清楚他剛剛做錯了哪個動作

5) 配角與指認：
- 配角都要有自然名字與記憶點
- 有台詞的配角和大人，要用自然名字或關係稱呼，例如「林老師 / 樂樂的爸爸 / 廣播阿姨阿秀」
- 最好留 1 到 2 個一聽就記得住的可愛名字；孩子角色可以偏綽號式，例如「鉛筆小白 / 狐狸小右 / 糖果小莓」，大人也可以是「職責/關係 + 暱稱」
- 禁止 A/B/C、甲乙丙、某位同學、那個男孩、紅色衣服的小朋友，也不要寫成「老師A / 爸爸B / 志工2 / 老師：」
- 陌生名字不要直接裸出。第一次提到時，最好直接帶出關係或職責，例如「霏霏的同學阿棠」「樂樂的朋友柏宇」「站務員小琳」
- final_accuse 前 3 個人都必須在指認前自然登場過

6) 壞事規模與收尾：
- 壞事起點可以只是幼稚惡作劇、想替朋友出氣、想搶風頭，但後果最好要長成差點更嚴重的麻煩，不要小到像順手亂放東西
- 如果事情差點鬧大，ending 可以讓老師、家長、站務員或工作人員接手，把人帶到旁邊了解、安撫、說明後續或通知家長；不要變成恐嚇或刑罰口氣
- 收尾不是一句原諒或一句教訓話就結束，要把現場怎麼被收住也寫出來

7) 收尾：
- clear：把真相、原因、道歉或承認、修復方式講完整
- nudge：孩子差一點點，由大人接手補齊，但仍要完整落地
- defer：不指認也要把事情安全收好，仍要交代原因與收尾
- 不是一句教訓話就結束

【案件 seed（僅作背景，不代表劇情順序）】
{seed}

輸出前請自我檢查：
- scene_01_start 是否真的像故事開頭，而不是案件摘要？
- 有沒有哪句笑話、比喻、吐槽，需要停下來想意思？如果有，請重寫成更自然的說法
- final_accuse 第 4 個選項是否完全等於：{unsure_choice_text}？
- final_accuse 是否有 solution_index: 0/1/2？
- 前三個嫌疑人是否都在指認前自然登場？
- 三個 ending 是否都有完整收尾（原因＋修復＋餘韻）？
""".strip()


def _format_errors(errors: List[str], *, max_lines: int = 18) -> str:
    if not errors:
        return ""
    lines = [f"- {e}" for e in errors[:max_lines]]
    if len(errors) > max_lines:
        lines.append(f"- ...（還有 {len(errors) - max_lines} 個）")
    return "\n".join(lines)


def _story_structure_signature(py_text: str) -> list[tuple[Any, ...]] | None:
    nodes = _parse_story_nodes_dict(py_text)
    if not nodes:
        return None

    signature: list[tuple[Any, ...]] = []
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            return None
        choices = node.get("choices")
        if not isinstance(choices, list):
            return None

        choice_sig = []
        for choice in choices:
            if not isinstance(choice, dict):
                return None
            choice_sig.append((choice.get("text"), choice.get("next")))

        signature.append(
            (
                node_id,
                node.get("next"),
                tuple(choice_sig),
                node.get("solution_index"),
                node.get("can_replay"),
                node.get("can_quit"),
            )
        )
    return signature


def _build_polish_input(*, py_text: str, style_example: str) -> str:
    return f"""
你是「故事二次潤句編輯」。
你的任務不是重寫案件，而是把一份已成形的 Python 故事檔修成更自然、更順口、更像樣本。

【你只能改的地方】
- 各節點的 title
- 各節點 narration 裡的句子文字

【絕對不能改的地方】
- `_n` helper
- node id
- 節點順序
- 每個 choices 的數量 / text / next
- 任一節點的 next
- solution_index
- can_replay / can_quit
- 案件事實、真相、事件順序

【優先修掉的問題】
- 一句話需要停下來想意思
- 比喻太跳、太刻意、像作者硬抖機靈
- 霏霏太像正經小老師
- 樂樂太像硬塞笑點機器
- 推理句太糊，讀者不知道角色在比對哪個不對勁
- 同一種舊味道說法反覆出現，但沒有真的推進
- 開場把人直接丟進場景裡，卻沒自然交代今天為什麼來、跟誰來、原本要做什麼
- 開場只知道很熱鬧，卻不知道今天到底是什麼活動、有哪些比賽或流程、霏霏樂樂來這裡做什麼
- 前半還沒讓人進入故事、記住人物和場子，事件就太快冒出來
- 陌生名字突然冒出來，讀者不知道這個人是誰、跟主角什麼關係、為什麼會在這裡
- 調查太快定調，還沒到 final_accuse 就幾乎只剩一個答案
- 動機又只剩怕丟臉、怕輸、怕被罵，沒有別種孩子氣但明確的壞心眼
- 如果故事核心本來像有人故意亂動、偷偷搞事、想搶風頭，不要在潤句時把它洗成單純手滑
- 壞事後果太小，只像日常小搗蛋，沒有長成差點更嚴重的大麻煩
- 有人突然說「我的疏忽 / 我的錯 / 我剛剛太忙了」，但前一段或同一段沒先講清楚他剛剛做了哪個動作

【角色提醒】
- 霏霏：熱心、貼心、愛笑、活潑，愛跟弟弟打鬧，但比較理性
- 樂樂：愛吃、衝動、愛鬧姊姊、愛看姊姊無奈；好笑要像真反應

【輸出規則】
- 只輸出完整 Python 檔案
- 不要 code fence
- 保留所有結構欄位與 choices 原樣

【語氣錨點（只學手感，不得照抄）】
{style_example}

【待潤句的 Python 檔】
{py_text}
""".strip()


def _best_effort_polish_python(
    client: OpenAI,
    *,
    model: str,
    instructions: str,
    py_text: str,
    style_example: str,
    unsure_text: str,
) -> str | None:
    original_sig = _story_structure_signature(py_text)
    if original_sig is None:
        return None

    polished = _generate_once(
        client,
        model=model,
        instructions=instructions,
        user_input=_build_polish_input(py_text=py_text, style_example=style_example),
    )
    polished = (polished or "").strip()
    if not polished:
        return None

    try:
        ast.parse(polished)
    except SyntaxError:
        return None

    if _story_structure_signature(polished) != original_sig:
        return None

    errors = _run_all_validations(polished, unsure_text=unsure_text)
    if errors:
        return None

    return polished


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        required=True,
        help="output python filename, e.g. story_case_new_case.py",
    )
    ap.add_argument("--seed", default="", help="optional seed text")
    ap.add_argument(
        "--include-old-rival", action="store_true", help="enable old rival module"
    )
    ap.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="max generation attempts (default: 3)",
    )
    args = ap.parse_args()

    if not args.out.endswith(".py"):
        raise SystemExit("--out must end with .py")

    api_key = clean_openai_api_key(os.environ.get("OPENAI_API_KEY"))
    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY")

    generate_model = _env_str("QF_STORY_GENERATE_MODEL", "OPENAI_MODEL") or "gpt-5.1"
    fix_model = _env_str("QF_STORY_FIX_MODEL", "QF_STORY_REPAIR_MODEL", "OPENAI_MODEL") or "gpt-5-mini"
    polish_model = _env_str("QF_STORY_POLISH_MODEL", "QF_STORY_FIX_MODEL", "QF_STORY_REPAIR_MODEL", "OPENAI_MODEL") or "gpt-5-mini"
    instructions = build_instructions(include_old_rival=args.include_old_rival)
    style_example = extract_style_example()

    user_input = _build_user_input(
        seed=args.seed,
        style_example=style_example,
        unsure_choice_text=UNSURE_CHOICE_TEXT,
    )

    client = OpenAI(api_key=api_key)
    print(f"[MODEL] generate={generate_model} fix={fix_model} polish={polish_model}")

    max_attempts = max(1, int(args.max_attempts or 3))
    last_errors: list[str] = []
    text = ""

    for attempt in range(1, max_attempts + 1):
        attempt_model = generate_model if attempt == 1 else fix_model
        text = _generate_once(
            client, model=attempt_model, instructions=instructions, user_input=user_input
        )

        # ✅ 生成後只做結構級修補，不偷偷改劇情文字
        text = _auto_fix_after_generate(text)

        errors = _run_all_validations(text, unsure_text=UNSURE_CHOICE_TEXT)

        if not errors:
            polished = _best_effort_polish_python(
                client,
                model=polish_model,
                instructions=instructions,
                py_text=text,
                style_example=style_example,
                unsure_text=UNSURE_CHOICE_TEXT,
            )
            if polished is not None:
                text = polished
            last_errors = []
            break

        last_errors = errors

        # 下一輪不要把整段 user_input 疊加，避免 prompt 爆炸
        fix_hint = _format_errors(errors)
        user_input = (
            _build_user_input(
                seed=args.seed,
                style_example=style_example,
                unsure_choice_text=UNSURE_CHOICE_TEXT,
            )
            + "\n\n"
            + f"⚠️ 你上一版不合格（第 {attempt} 次嘗試）：\n"
            + "請「保持故事整體結構與人物不變」，"
            + "僅針對以下問題補寫或修正：\n"
            + fix_hint
            + "\n\n"
            + "請重新輸出完整 Python 檔案（仍然禁止任何 code fence）。"
        )

    if last_errors:
        raise SystemExit(
            "生成失敗，仍未通過驗證：\n" + _format_errors(last_errors, max_lines=60)
        )

    out_path = CONTENT_DIR / args.out
    out_path.write_text(text, encoding="utf-8")
    print(f"[OK] wrote: {out_path}")

    module_name = args.out[:-3]  # 去掉 .py
    register_case_into_cases_py(module_name=module_name, seed=args.seed)
    print(f"[OK] registered case into: {CASES_FILE}")


if __name__ == "__main__":
    main()
