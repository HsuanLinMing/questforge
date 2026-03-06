# QuestForge Story Case Template v2 (Narration-only, Scene Audio Friendly)

你要輸出「可直接執行的 Python dict」：

```py
STORY_NODES = { ... }
```

本模板以 `story_case_class_party_bag.py` 的結構為準：  
- 單一 narration 版本（不使用 beats）
- narration 統一使用「角色：內容」換行，段落之間用 `\n\n`
- 每個 scene 對應一段可生成語音的 narration（適合「每 scene 產生一個語音檔」的強快取流程）

---

## 0) 必守原則
- 兒童友善、小一友善：不血腥、不恐嚇、不羞辱，不把推理做成對錯題
- 強調「觀察/證據/確認」；永遠保留「交給老師」為安全正確選擇
- 線索與 evidence 用中文
- 不用「線索數量」卡關；指認永遠可進

---

## 1) 硬性輸出骨架（節點結構）
### 1.1 helper
檔案內必須有：

```py
def _n(*lines: str) -> str:
    return "\n\n".join([x for x in lines if (x or "").strip()])
```

### 1.2 節點命名（建議序）
- `scene_01_start`：開場（較長，鋪陳後才進事件）
- `scene_02_incident`：事件爆點（失物/誤會/衝突）
- `scene_03_investigate_room`：進入調查場景/空間
- `scene_04_xxx`：關係人說法
- `scene_05_xxx`：小線索/小發現
- `scene_06_xxx`：第二個關係人/更多資訊
- `scene_07_before_accuse`：收束、提醒只講觀察
- `final_accuse`：指認（一定要有「我還不確定，先去問清楚再說」）
- `scene_10_ending_clear`：推理分足夠的結尾
- `scene_10_ending_nudge`：差一點（AI/霏霏補一句）
- `scene_10_ending_defer`：交給老師/先確認再結論的結尾
- `quit`：故事結束（固定）

> 注意：結尾三種不一定都會被跑到；引擎會依評分把 `final_accuse` 後導向不同 ending。  
> 但你仍要輸出三種 ending，供引擎選用。

---

## 2) choices 規則（非常重要）
### 2.1 自動播放節點（scene_*）
- 除了 `final_accuse` 與 `quit` 等互動節點以外，所有的 `scene_*` 都必須是 Narration-only：
  - `choices: []` （**必須為空陣列，絕對不能有「繼續聽故事」這種選項**）
  - 必須在節點層級加上 `next` 屬性，指向下一個節點：`"next": "<下一節點>"`

### 2.2 指認節點（final_accuse）
- `final_accuse` 必須有 4 個選項（可依案件調整嫌疑人名單），其中一定包含：
  - 「我還不確定，先去問清楚再說」→ `next: "quit"`
- 其他三個為嫌疑人 → `next: "quit"`
- 不在 `final_accuse` 幫孩子複習線索、不提示正解（由引擎評分 + ending 分流呈現回饋）

### 2.3 quit
- `quit` 節點 `choices: []`
- 建議保留：
  - `can_replay: True`
  - `can_quit: True`

---

## 3) narration 寫法規範
- 一次 narration 內可包含多句對話，但必須保持：
  - 「角色：內容」格式
  - 用 `_n(...)` 分段（每段不宜太長，方便 TTS/快取）
- 每次玩家做出選擇後（尤其是 investigation/accuse 流程），可加入 1~2 句自然對話，解釋「為什麼找到這個線索」（不裁決、不下結論）

---

## 4) （可選）世界觀模組：理念型反派／老對手
- 此角色屬於全域世界觀模組：不必每案出現
- 若此案啟用：
  - 只能以「引導者/對峙者/留痕者」方式呈現
  - 不可把違法行為浪漫化
  - 不可讓主角直接抓到他（一般案件）
