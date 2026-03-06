# QuestForge Architecture

QuestForge 是一個 **AI 驅動的互動式偵探故事遊戲系統**。

系統整合：

- AI故事生成
- TTS語音生成
- Flutter互動遊戲
- Story Pool
- Background Worker

目標是打造一個 **可持續生成故事的 AI 偵探遊戲平台**。

---

# 系統總架構

```

Flutter App
│
▼
Cloudflare CDN
│
▼
Render (FastAPI API Server)
│
├── Redis
│      Story Pool
│      Task Queue
│
├── OpenAI
│      Story Generation
│      TTS Generation
│
└── Cloudflare R2
Audio Storage

```

---

# 專案結構

```

QuestForge
│
├── questforge_server
│       FastAPI backend
│
├── questforge_flutter_demo
│       Flutter client
│
├── src/questforge
│       AI story engine
│
│       ├── ai
│       │      runtime_story_nodes_generator_v1.py
│       │      story_spec_v1.py
│       │      prompt_assets.py
│       │
│       ├── engine
│       │      session.py
│       │
│       ├── content
│       │      example stories
│       │
│       └── contracts
│              story_nodes_v1
│
├── README.md
└── ARCHITECTURE.md

```

---

# Story Generation Pipeline

QuestForge 使用 AI 即時生成故事。

流程如下：

```

Player Start Game
│
▼
POST /v1/game/start
│
▼
FastAPI Server
│
▼
Runtime Story Generator
│
▼
OpenAI API
│
▼
StoryNodes JSON
│
▼
Validator
│
▼
Return to Flutter

```

---

# StoryNodes 資料結構

QuestForge 使用 **StoryNodesPackage v1** 作為遊戲資料結構。

主要包含：

```

scene_01_start
scene_02_clue
scene_03_choice
scene_04_result
scene_05_reveal

```

每個 node 包含：

```

id
narration
dialogue
choices
next

```

Flutter 依照 node 進行遊戲流程。

---

# TTS Pipeline

AI 生成故事後，系統會生成語音。

流程：

```

StoryNodes
│
▼
Split narration
│
▼
OpenAI TTS
│
▼
Generate wav files
│
▼
Upload to R2
│
▼
Return audio URLs

```

音檔範例：

```

tts/
story_id/
0.wav
1.wav
2.wav

```

---

# Story Pool System

為了避免玩家等待 AI 生成故事，系統使用 **Story Pool**。

Story Pool 狀態：

```

generating
ready
tts_ready

```

流程：

```

Worker generates story
│
▼
Story added to pool
│
▼
Player requests story
│
▼
Story taken from pool
│
▼
Worker generates new story

```

---

# Background Worker

Worker 負責：

- AI故事生成
- TTS生成
- Story Pool 補貨

流程：

```

Worker Loop
│
▼
Check Story Pool
│
▼
If pool < threshold
│
▼
Generate story
│
▼
Generate TTS
│
▼
Store to pool

```

---

# Redis

Redis 用於：

- Story Pool
- Task Queue
- Session
- Rate Limit

資料例子：

```

story_pool_ready
story_pool_generating
story_pool_tts_ready

```

---

# Cloudflare R2

R2 用於儲存：

- TTS音檔
- AI故事
- 未來圖片 / 影片

優點：

- 低成本
- CDN整合
- 無出站費

---

# Flutter Client

Flutter 負責：

- UI / UX
- 玩家選擇
- TTS播放
- StoryNode渲染

流程：

```

Start Game
│
▼
Call API
│
▼
Receive StoryNodes
│
▼
Render UI
│
▼
Play TTS

```

---

# 未來架構升級

Production 版本：

```

Flutter
↓
Cloudflare CDN
↓
API Gateway
↓
Render FastAPI
↓
Redis Queue
↓
AI Worker Cluster
↓
OpenAI API
↓
R2 Storage

```

未來可能新增：

- Story Ranking
- AI Editor
- Voice Cloning
- User Profiles
- Story Analytics

---

# 設計原則

QuestForge 的設計原則：

- AI-first
- Data-driven stories
- Stateless API
- Background generation
- CDN optimized

---

# 系統目標

QuestForge 的長期目標：

打造一個

**AI互動故事平台**

讓孩子可以：

- 聽故事
- 做推理
- 學習同理心
- 培養觀察力

主角：

- 霏霏小偵探
- 樂樂小偵探
```

---

# 你現在的專案會變成

```
QuestForge
│
├─ README.md
├─ ARCHITECTURE.md
│
├─ questforge_server
│
├─ questforge_flutter_demo
│
└─ src/questforge
```

