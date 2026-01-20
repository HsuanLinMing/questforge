# QuestForge Story Nodes Schema (Narration-only)

版本：v1 (2026-01)

目的：讓每個故事案件都用**同一種**資料格式（`title + narration + choices`），方便：
- CLI / Flutter UI 直接顯示
- 引擎（GameSession）做流程跳轉
- 自動驗證（lint）早爆早修

---

## 1) STORY_NODES（故事節點）

每個案件檔案提供：

```py
STORY_NODES: dict[str, dict]
