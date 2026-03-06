# QuestForge

QuestForge 是一個 **AI 驅動的兒童偵探故事遊戲引擎**。

系統使用 **Python FastAPI + OpenAI + Flutter**，  
可以即時生成偵探故事、語音旁白，並讓玩家透過 Flutter App 進行互動推理。

目前主角為：

- 霏霏小偵探
- 樂樂小偵探

故事核心：

- 推理
- 同理心
- 反霸凌
- 觀察力

---

# 系統架構

```

Flutter App
│
▼
Cloudflare CDN
│
▼
Render (FastAPI Server)
│
├── Redis
│     story pool
│     queue
│
├── OpenAI
│     AI story generation
│     TTS generation
│
└── Cloudflare R2
TTS audio storage

```

---

# 專案結構

```

QuestForge
│
├── questforge_server
│      FastAPI backend
│
├── questforge_flutter_demo
│      Flutter game client
│
├── src/questforge
│      AI story engine
│
└── README.md

```

---

# 系統組件說明

## Render

Render 是 QuestForge 的 **雲端後端 Server**。

負責：

- FastAPI API
- AI故事生成
- TTS語音生成
- 提供 API 給 Flutter

API 例子：

```

POST /v1/game/start
GET  /v1/game/tts_status

```

部署網址：

```

[https://questforge-2dqc.onrender.com](https://questforge-2dqc.onrender.com)

```

---

## Redis

Redis 是 **高速記憶體資料庫**。

用途：

- Story Pool
- Background Queue
- Session
- Rate Limit

範例：

```

story_pool_ready
story_pool_generating
story_pool_tts_ready

```

---

## Cloudflare

Cloudflare 提供：

- CDN 加速
- HTTPS
- 防 DDoS
- Cache

資料流程：

```

Flutter App
↓
Cloudflare
↓
Render Server

```

---

## Cloudflare R2

R2 是 **Object Storage（檔案儲存）**。

用途：

- TTS 音檔
- AI故事 JSON
- 未來圖片 / 影片

範例結構：

```

tts/
story_id/
0.wav
1.wav
2.wav

```

音檔 URL：

```

[https://cdn.questforge.app/tts/story_id/0.wav](https://cdn.questforge.app/tts/story_id/0.wav)

```

---

# API 測試

## 啟動遊戲

```

curl -X POST [https://questforge-2dqc.onrender.com/v1/game/start](https://questforge-2dqc.onrender.com/v1/game/start)

```

---

## 查詢 TTS 狀態

```

curl "[https://questforge-2dqc.onrender.com/v1/game/tts_status?view_fp=xxxxx](https://questforge-2dqc.onrender.com/v1/game/tts_status?view_fp=xxxxx)"

```

---

# 本地開發

啟動 FastAPI：

```

uvicorn questforge_server.main:app --reload --port 8000

```

測試 API：

```

curl -X POST [http://127.0.0.1:8000/v1/game/start](http://127.0.0.1:8000/v1/game/start)

```

---

# QuestForge Runtime 流程

```

1. Flutter App 啟動
2. 呼叫 /v1/game/start
3. Server 從 Story Pool 取得故事
4. Server 回傳 StoryNodes
5. Flutter 顯示故事
6. TTS 播放語音
7. Background Worker 生成新故事

```

---

# 未來架構升級

Production 架構：

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
AI Worker
↓
OpenAI
↓
R2 Storage

```

---

# 技術棧

Backend

- Python
- FastAPI
- Redis
- OpenAI API

Frontend

- Flutter
- just_audio
- Riverpod / Provider

Storage

- Cloudflare R2

Infrastructure

- Render
- Cloudflare CDN

---

# 專案目標

QuestForge 的目標是建立一個：

AI + 教育 + 遊戲

的互動式故事平台。

未來計畫：

- AI生成故事
- 多角色語音
- Flutter App 上架
- AI故事生成系統
- 家庭教育互動遊戲

---

# 作者

QuestForge  
AI Detective Story Engine

主角：

霏霏小偵探  
樂樂小偵探
```

