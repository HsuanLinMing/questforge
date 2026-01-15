# QuestForge Story Case Template v1 (Hard Skeleton)

你要輸出「可直接執行的 Python dict」：
STORY_NODES = { ... }

【硬性骨架（不得增減互動次數）】
- 故事採用「方案A：2次互動法」
- 恰好兩個互動節點：
  1) mid_reason（第1次互動：輕推理，孩子像主角插一句）
  2) final_accuse（第2次互動：指認/交給老師）
- 其他節點都要是「自動播放主線」節點（auto-continue）
  - 這類節點 choices 必須只有 1 個，且 text 固定為「繼續聽故事」

【節點命名約定（必遵守）】
- start：開頭（一定是 auto-continue）
- scene_01 / scene_02 / scene_03 / scene_04：主線（全部 auto-continue）
- mid_reason：第一次互動（3 個選項，必有「我還不確定/先看看」類）
- scene_05 / scene_06：互動後繼續演（auto-continue，不可直接進結尾）
- final_accuse：第二次互動（4 個選項=3嫌疑人+「我還不確定交給老師」）
- ending_result：結局（必有 lesson:list[str]，choices 1個「結束故事」）
- quit：結束（choices 空）

【auto-continue 規則】
- start / scene_xx / teacher_notice / cool_down 等「非互動」節點：
  - choices = [{"text":"繼續聽故事","next":"..."}] 只能 1 個
- mid_reason / final_accuse / ending_xxx 不屬於 auto-continue

【人物/口吻】
- 固定主角：霏霏（常忘東忘西但有主見）、樂樂（調皮搞蛋但暖心）
- 敘事主要用對話推進，不要霏霏變旁白老師
- 不要出現「如果你在這裡你會怎麼說？」
- 第一次互動：孩子要像「插一句」，彷彿替主角說一句話（不是第三人稱旁白）

【案件填空（由你自行生成）】
- 場景：校園/教室/午餐
- 事件：便當被動過（不描述暴力/恐嚇/犯罪）
- 嫌疑人：3 位（名字有記憶點 + 特徵）
- 老師：要在中段就出現（scene_04 或 scene_05 起）

【必備節奏】
- 開頭要夠長：至少 2~4 段自然對話/小互動，再進事件
- mid_reason 之後至少再有 2 個 scene 節點繼續演，才進 final_accuse
- final_accuse 前必有「降溫對話」節點（cool_down 類 scene）

【你必須輸出以下節點（key 必須存在，不能少）】
start
scene_01
scene_02
mid_reason
scene_03
scene_04
final_accuse
ending_result
quit
ending_wrong (可選，但建議加：指認錯誤/證據不足)

【mid_reason choices（固定數量=3）】
- 選項都是「我覺得…」的插話口吻（像主角講一句）
- 必須包含一個「我還不確定/先看看」類選項
- 每個選項可有 after，after 必須是短短一段對話/動作（不標示“線索”）

【final_accuse choices（固定數量=4）】
- 3嫌疑人 + 1「我還不確定，交給老師」

【ending_result】
- lesson: list[str] 必須存在（3 條即可）
- choices 只能 1 個：{"text":"結束故事","next":"quit"}

開始輸出 STORY_NODES。
