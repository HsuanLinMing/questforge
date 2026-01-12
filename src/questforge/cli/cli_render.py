from __future__ import annotations

from typing import Optional

from questforge.core.models import DetectiveState
from questforge.engine.views import NodeView


def show_status(state: DetectiveState) -> None:
    """CLI：顯示目前回合、線索、旗標（除錯 / 教學用）。"""
    if state.clues:
        readable = [state.clue_labels.get(k, k) for k in sorted(state.clues)]
        clues = "、".join(readable)
    else:
        clues = "（還沒有）"

    flags = "、".join(sorted(state.flags)) if state.flags else "（無）"

    print("-" * 40)
    print(f"回合：{state.turn}")
    print(f"線索：{clues}")
    print(f"旗標：{flags}")
    print("-" * 40)


def trace(
    *,
    state: DetectiveState,
    case_title: str,
    current: str,
    chosen_idx: Optional[int],
) -> None:
    """CLI：追蹤用輸出（不影響遊戲）。"""
    clues = ",".join(sorted(state.clues)) if state.clues else "-"
    pick = f" choice={chosen_idx}" if chosen_idx is not None else ""
    print(
        f"[TRACE] turn={state.turn} case={case_title} node={current}{pick} clues={clues}"
    )



def render_view(view: Any) -> None:
    """CLI：顯示目前節點內容。

    支援：
    - NodeView（choices）
    - EndingCheckView（options）
    """
    print(f"\n【{getattr(view, 'title', '')}】")
    print(getattr(view, "narration", ""))

    # EndingCheckView: options: List[tuple[str, str]]
    options = getattr(view, "options", None)
    if options:
        print("\n你想怎麼做？")
        for opt_id, label in options:
            print(f"  {opt_id}. {label}")

        print(
            "\n（輸入數字選擇，C=線索，N=筆記，P=存檔列表，R=重播，S=儲存，L=讀檔，Q=離開）"
        )
        return

    # NodeView: choices
    choices = getattr(view, "choices", None) or []
    if not choices:
        return

    print("\n你想怎麼做？")
    for c in choices:
        print(f"  {c.index}. {c.text}")

    print(
        "\n（輸入數字選擇，C=線索，N=筆記，P=存檔列表，R=重播，S=儲存，L=讀檔，Q=離開）"
    )