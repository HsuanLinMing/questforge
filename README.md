QuestForge

一個以 Python 為核心的文字冒險推理遊戲
結合資料驅動遊戲引擎 × 教育導向故事 × 未來 AI 劇情生成

📁 專案結構（Project Structure）
src/questforge/
├── core/
│   ├── models.py          # 核心資料模型（玩家、遊戲狀態）
│   └── __init__.py
│
├── engine/
│   ├── game.py            # 遊戲主引擎（流程控制、節點渲染、判定）
│   └── __init__.py
│
├── content/
│   ├── cases.py           # 案件清單與規則設定
│   ├── story_case_theft.py
│   ├── story_case_injury.py
│   ├── story_case_bullying.py
│   └── __init__.py
│
├── ai/
│   ├── prompts.py         # AI 劇情生成提示（規劃中）
│   └── schema.md          # AI 輸出格式規範（規劃中）
│
└── main.py                # 專案入口點

🧠 架構設計說明（Architecture Overview）

QuestForge 採用 資料驅動（Data-Driven）＋ 規則引擎（Rule Engine） 的設計方式，
將「故事內容」與「遊戲邏輯」完全分離，方便擴充、維護與未來 AI 整合。

core/ — 核心資料模型（Domain Models）

用途

放置純資料結構

不包含任何遊戲流程或故事邏輯

目前包含

Player：玩家狀態（生命、金幣、線索）

GameState：整體遊戲狀態（回合數、玩家）

設計原則

使用 @dataclass 表示資料結構

不負責「怎麼玩」，只負責「現在狀態是什麼」

Flutter 類比：
models/ + Provider / Riverpod 裡的 State class

engine/ — 遊戲引擎（Game Engine）

用途

控制整個遊戲流程

負責處理：

故事節點顯示

玩家選項輸入

推理成功 / 失敗判定

案件切換

重要特性

不寫任何故事內容

不關心案件細節

僅依照「規則」與「資料」運作

Flutter 類比：
Controller / ViewModel + Navigator 流程控制

content/ — 故事與案件資料（Game Content）

用途

放置所有案件與故事節點

完全是資料（dict / JSON-like）

可以手寫，也可以由 AI 生成

內容包含

cases.py：案件清單、起始節點、解案規則

story_case_*.py：各類型案件的故事節點

設計重點

每個案件都是「短篇」

多個短篇可串成「長篇章節」

替換故事內容不需要修改引擎

Flutter 類比：
API Response / CMS 內容 / 本地 JSON

ai/ — AI 劇情生成（規劃中）

定位

AI 不控制遊戲邏輯

AI 僅負責生成「故事資料」

未來用途

生成不同版本的案件

產生多樣化線索與角色

輸出內容必須符合 schema.md 規範

設計理念

AI 是編劇，引擎是導演，規則由開發者掌控

🎮 專案介紹（Project Overview）

QuestForge 是一個以 Python 為核心的文字冒險推理遊戲專案，
主題為 「菲菲小偵探＆樂樂小偵探」的推理冒險故事。

遊戲對象

國小低年級（約 6–8 歲）

學習目標

同理心

反霸凌

正確處理衝突

問題解決能力

🎯 專案目標

建立一個可擴充的 Python 遊戲引擎

使用資料驅動方式設計故事與案件

為未來 AI 輔助敘事做好結構準備

作為 Backend / AI 相關職位的作品展示

🚧 目前進度（Current Status）

Day 1

Python 環境建置

Git / GitHub 設定完成 ✅

Day 2

核心遊戲流程

案件與故事節點系統（進行中）

✨ 規劃功能（Planned Features）

文字冒險推理遊戲

多案件、隨機案件選擇

短篇案件 → 長篇章節故事

線索收集與推理判定

正向教育結局設計

AI 生成故事事件與對話（規劃中）

語音輔助（TTS，規劃中）

🛠 技術棧（Tech Stack）

Python 3

FastAPI（規劃中）

SQLite / PostgreSQL（規劃中）

LLM API（規劃中）