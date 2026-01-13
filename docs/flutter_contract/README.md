# QuestForge – Flutter UI Contract v1

本資料夾定義 **QuestForge Engine → Flutter UI** 之間的「穩定資料契約（Contract）」。

目標：
- Flutter UI **不需要理解引擎邏輯**
- 只根據 `commands` + `meta` 繪製畫面
- Contract **可版本化、可向後相容**

目前版本：
- **reasoning_contract_v1**

---

## 一、整體資料流

Engine 每一次 `step()` 回傳：

```json
{
  "view": { ... } | null,
  "events": ["文字事件"],
  "is_over": false,
  "commands": [
    { "type": "...", "...": "..." }
  ]
}
