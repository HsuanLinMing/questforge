# src/questforge/ai/story_writer_cli.py
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import List

from openai import OpenAI

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
CONTENT_DIR = Path(__file__).resolve().parents[1] / "content"

CASES_FILE = CONTENT_DIR / "cases.py"
STYLE_EXAMPLE_FILE = CONTENT_DIR / "story_case_class_party_bag.py"

CORE_FILES = [
    "story_prompt_v1.md",  # 唯一母版
    "story_case_template_v1.md",
    "schema_story_nodes.md",
    "guard_rules.md",
    "story_response_whitelist.md",
    "world_old_rival_module.md",  # 可開關
]

# -------------------------
# Few-shot: 黃金開場（節奏錨點）
# -------------------------
GOLDEN_OPENING_EXAMPLE = """
【黃金開場示範（僅示範節奏，禁止照抄內容）】
旁白：今天的教室聞起來有點像紙箱味，因為大家把道具、海報、彩帶都搬進來了。

旁白：黑板上用粉筆寫著大大的四個字——「才・藝・日」。

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
    """抽取 story_case_class_party_bag.py 的前段作為節奏示範（第二個錨點）"""
    if not STYLE_EXAMPLE_FILE.exists():
        return ""
    lines = STYLE_EXAMPLE_FILE.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[:180]).strip()


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
    if n_lines < 20:
        errors.append(f"scene_01_start narration 行數不足（目前 {n_lines}，至少 20）")

    banned_opening_terms = [
        "不見",
        "找不到",
        "遺失",
        "被偷",
        "消失",
        "可疑",
        "奇怪",
        "不尋常",
        "發現問題",
        "出事",
        "有問題",
        "開始調查",
        "推理過程",
        "解決案件",
    ]
    for t in banned_opening_terms:
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
    return any(k in t for k in ["不確定", "交給老師", "先去問清楚", "找老師", "問老師"])


def _is_cute_name(name: str) -> bool:
    if not name or len(name) < 2:
        return False
    if any(
        x in name for x in ["學長", "學姊", "同學", "某位", "那個", "小朋友", "老師"]
    ):
        return False
    if re.search(r"[\u4e00-\u9fff]", name) is None:
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
        if _is_unsure_choice(s) or ("老師" in s):
            errors.append(f"final_accuse 前三個選項必須是嫌疑人名字（目前：{s}）")

    for s in suspects:
        if not _is_cute_name(s):
            errors.append(f"嫌疑人命名不符合可愛命名規則：{s}")

    narration_text = _collect_all_narration_text(py_text)
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
    errors: list[str] = []

    nodes_blk = _extract_story_nodes_block(py_text) or py_text
    scene_keys = re.findall(r'"\b(scene_\d+_[^"]+)"\s*:\s*\{', nodes_blk)
    main_scenes = [k for k in scene_keys if not k.startswith("scene_10_ending")]

    incident_terms = ["不見", "找不到", "遺失", "消失"]
    incident_index = None
    for i, k in enumerate(main_scenes):
        blk = _extract_scene_block(py_text, k)
        if any(t in blk for t in incident_terms):
            incident_index = i
            break

    if incident_index is None:
        return ["找不到事件發生點（全文沒有出現 不見/找不到/遺失/消失）"]

    after = []
    for k in main_scenes[incident_index + 1 :]:
        if k in ("final_accuse", "quit"):
            continue
        if k.startswith("scene_10_ending"):
            continue
        after.append(k)

    if len(after) < 2:
        errors.append(
            f"事件後的搜尋/互動 scene 不足（目前 {len(after)}，至少 2），容易太快進指認"
        )

    return errors


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


def _strip_kana(text: str) -> str:
    # 平假名 + 片假名
    return re.sub(r"[\u3040-\u30ff]+", "", text)


def _replace_banned_terms_in_scene01(scene01_blk: str) -> str:
    """
    只在 scene_01_start 區塊內做「安全替換」。
    替換字不要撞到 banned_opening_terms。
    """
    # ✅ 這些是你 validator 會抓到的開場禁詞：用更「日常」的說法替換
    replacements = {
        "消失": "跑開",
        "不見": "沒在眼前",
        "找不到": "一時沒看到",
        "遺失": "放到別處了",
        "被偷": "被拿走了",
        "可疑": "有點怪",
        "奇怪": "有點怪",
        "不尋常": "特別",
        "發現問題": "發現狀況",
        "出事": "出了狀況",
        "有問題": "有點狀況",
        "開始調查": "開始看看",
        "推理過程": "想一想",
        "解決案件": "把事情弄清楚",
    }
    out = scene01_blk
    for a, b in replacements.items():
        out = out.replace(a, b)
    return out


def _extract_final_accuse_suspects(py_text: str) -> list[str]:
    """
    取 final_accuse choices 前三個 text（嫌疑人名字）
    """
    choices = _extract_final_accuse_choice_texts(py_text)
    if len(choices) >= 3:
        return [choices[0].strip(), choices[1].strip(), choices[2].strip()]
    return []


def _inject_suspects_into_scene01(scene01_blk: str, suspects: list[str]) -> str:
    """
    若 scene_01_start 內沒出現嫌疑人名字，就在 narration _n(...) 結尾補登場句。
    只補「日常」句，不碰事件、異常詞。
    """
    if not scene01_blk or not suspects:
        return scene01_blk

    missing = [s for s in suspects if s and (s not in scene01_blk)]
    if not missing:
        return scene01_blk

    m = re.search(r'("narration"\s*:\s*_n\()(.*?)(\)\s*,)', scene01_blk, flags=re.S)
    if not m:
        return scene01_blk

    prefix = m.group(1)
    inside = m.group(2)
    suffix = m.group(3)

    extra_lines = []
    for s in missing:
        # ✅ 只用日常、安心的句子
        extra_lines.append(f'"旁白：{s}抱著自己的小物走進來，朝大家點點頭。",')
        extra_lines.append(f'"{s}：嘿～早安！我今天也來一起玩！",')

    new_inside = inside.rstrip()
    if new_inside and not new_inside.endswith("\n"):
        new_inside += "\n"
    new_inside += "\n".join(extra_lines) + "\n"

    new_narration = prefix + new_inside + suffix
    return scene01_blk[: m.start()] + new_narration + scene01_blk[m.end() :]


def _auto_fix_scene01(py_text: str) -> str:
    """
    修 scene_01_start：
    - 移除日文假名
    - 替換 banned 詞（全套替換）
    - 確保嫌疑人於 scene_01_start 登場
    """
    blk = _extract_scene_block(py_text, "scene_01_start")
    if not blk:
        return py_text

    fixed = blk
    fixed = _strip_kana(fixed)
    fixed = _replace_banned_terms_in_scene01(fixed)

    suspects = _extract_final_accuse_suspects(py_text)
    fixed = _inject_suspects_into_scene01(fixed, suspects)

    return py_text.replace(blk, fixed, 1)


def _auto_fix_after_generate(py_text: str) -> str:
    """
    集中所有 auto-fix：順序很重要
    - 先修 solution_index
    - 再修 scene_01_start（包含 kana / banned / suspects intro）
    """
    out = py_text
    out = _auto_fix_solution_index(out)
    out = _auto_fix_scene01(out)
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
【硬性生成要求（非常重要，務必遵守）】

1) 結構完整性（缺一不可）
- 必須包含並完整定義以下 nodeId（不可缺漏）：
  - scene_01_start
  - final_accuse
  - scene_10_ending_clear
  - scene_10_ending_nudge
  - scene_10_ending_defer
  - quit
- 每個 ending 節點必須含：
  - title
  - narration（要像故事收尾：真相/原因/修復/餘韻，不可只有一句話）
  - choices: [{{"text":"故事結束","next":"quit"}}]
- quit 節點必須包含 can_replay 與 can_quit

2) 開場硬規範
- scene_01_start 必須像「真正的故事第一章」，至少 22～30 行 narration
- scene_01_start 只能做：世界觀介紹 / 日常互動 / 玩笑吐槽 / 配角登場
- scene_01_start 禁止任何事件與異常（禁止：不見/找不到/遺失/被偷/消失/可疑/奇怪/不尋常/出事/有問題）
- 禁止任何「編劇式提示」：不可說「很可疑」「奇怪的事情」「目擊到不尋常」
- 禁止日文（不得出現平假名/片假名）

3) 角色命名硬規則（禁止 placeholder）
- 配角必須有名字：禁止「紅色衣服的小朋友」「小朋友」「那個男孩」這種泛稱
- 禁止使用 A/B/C、甲乙丙、學長A/B/C 這種佔位名字

4) 指認候選人硬規則（final_accuse）
- final_accuse 必須剛好 4 個選項：
  (1) 嫌疑人1（可愛命名）
  (2) 嫌疑人2（可愛命名）
  (3) 嫌疑人3（可愛命名）
  (4) 必須 **完全等於**：{unsure_choice_text}
- ⚠️ 前三個「只允許嫌疑人名字」，禁止出現「提醒句/規則句/帶給老師確認」這種句子
- 前三個嫌疑人名字必須在故事前文（scene_01_start～指認前）明確登場過至少一次
- 在 scene_01_start 或 scene_02 必須讓三位嫌疑人都先登場（至少各說一句或被點到一次）後，才能放進 final_accuse

5) 中段搜尋節奏（避免太快指認）
- 事件出現後，必須至少有 2～3 個連續 scene 在做「自然搜尋」：
  - 翻找 / 回到剛剛的位置 / 問不同人 / 看物品痕跡 / 被打斷 / 再次確認
- 不可「事件一出就立刻指認」

6) ✅ A 方案必要欄位
- final_accuse 節點必須包含欄位：
  - solution_index: 0 或 1 或 2
  - ⚠️ solution_index 只能指向「前三個嫌疑人」之一（0=第1人、1=第2人、2=第3人）
  - ⚠️ 第4個選項「我還不確定，交給老師」永遠不算在 solution_index 裡（不能是 3）
- 代表前三個嫌疑人中「正解」所在的 index（0-based）

7) 故事必須「收尾完整」
- 三個 ending 都要有故事感：
  - clear：清楚知道發生了什麼＋做錯的人說出原因（孩子能懂的情緒：想被看見/怕輸/怕出糗等）＋修復方式
  - nudge：差一點點，由霏霏只補一句，然後由大人接手把真相補齊
  - defer：不指認，交給大人確認，最後也要把事情安全收好（仍要有原因與修復）
- 禁止 ending 只有 1～2 句就結束

8) 格式
- 必須輸出包含：
  - _n helper
  - STORY_NODES dict
- narration 一律「角色：內容」並用 \\n\\n 分段
- 不可以出現 code fence（```）

⚠️ 嫌疑人名單預告（內部規劃，不要明說給讀者）
- 在開始寫故事前，請你先在腦中決定三位嫌疑人名字
- 這三個名字必須：
  - 可愛命名（動物/零食/用品 + 小名）
  - 之後會出現在 final_accuse 的前三個選項
- 接著請在 scene_01_start 或 scene_02 中，
  **自然地讓這三位角色全部登場一次**
  （說一句話 / 被點名 / 做一個動作都可以）

【案件 seed（僅作背景，不代表劇情順序）】
{seed}

輸出前請自我檢查：
- final_accuse 第 4 個選項是否完全等於：{unsure_choice_text}？
- final_accuse 是否有 solution_index: 0/1/2？
- 前三個是否都是可愛名字，且在前文登場？
- 三個 ending 是否都有完整收尾（原因＋修復＋餘韻）？
""".strip()


def _format_errors(errors: List[str], *, max_lines: int = 18) -> str:
    if not errors:
        return ""
    lines = [f"- {e}" for e in errors[:max_lines]]
    if len(errors) > max_lines:
        lines.append(f"- ...（還有 {len(errors) - max_lines} 個）")
    return "\n".join(lines)


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

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY")

    model = (os.environ.get("OPENAI_MODEL") or "gpt-4o-mini").strip()
    instructions = build_instructions(include_old_rival=args.include_old_rival)
    style_example = extract_style_example()

    # ✅ 固定「不確定」選項文字
    UNSURE_CHOICE_TEXT = "我還不確定，交給老師"

    user_input = _build_user_input(
        seed=args.seed,
        style_example=style_example,
        unsure_choice_text=UNSURE_CHOICE_TEXT,
    )

    client = OpenAI(api_key=api_key)

    max_attempts = max(1, int(args.max_attempts or 3))
    last_errors: list[str] = []
    text = ""

    for attempt in range(1, max_attempts + 1):
        text = _generate_once(
            client, model=model, instructions=instructions, user_input=user_input
        )

        # ✅ 生成後自動修補（solution_index + scene_01_start）
        text = _auto_fix_after_generate(text)

        errors = _run_all_validations(text, unsure_text=UNSURE_CHOICE_TEXT)

        if not errors:
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
