# QuestForge TODOs

## 下一階段：預載下一段音檔 (Prefetch TTS)

為了解決「因為需要先推進故事狀態才能拿到下一段 TTS 播放清單（音檔網址），導致點選後還是得等下載」的問題，需要進行真正的「預載」。

### 後端配合 (擇一方案)

**方案一：新增 API `GET /v1/game/peek_next?session_id=...`**
* 不推進 session state，只回傳「下一個 view + 其對應的 tts_playlist」。
* 好處：前端完全不需要自己去猜下一段的狀態。

**方案二：在 `view.meta` 增加 `prefetch_next_view_fp` 欄位**
* 讓 Flutter 可以提前打 `/v1/game/tts_status?view_fp=...` 預抓音檔。
* 好處：對後端改動較小，只要在生成節點時順便附上下一個階段的 view fingerprint 即可。

### Flutter 端配合

* 在播放當前節點的「倒數第二段開始時（或播放中期）」，就提前打 `peek_next` 或是 `/v1/game/tts_status?view_fp=prefetch_fp`。
* 將拿到的網址提前送出 Http Get 來 warm up cache 或下載到本地，這樣當真正點擊「繼續」切換到下一個畫面時，音頻便能秒播。
