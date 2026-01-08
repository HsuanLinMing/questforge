輸出必須是 JSON object（dict），key 是 node_id。
每個節點：
- title: string
- narration: string（最多 2 句短句）
- lesson: [string]（可選，只建議用在 ending_result，3~6 行）
- gain_clue: string（可選）
- choices: [{text: string, next: string}]
固定必備節點：
- start
- final_accuse
- ending_result
- ending_wrong
- quit
規則：
- 選項數：前段 3，中段 4，最多 5
- 嫌疑人固定 3 位，每位都有一個好記特徵
- 內容安全：不血腥、不恐怖、不死亡
- 結局正向、有教學意義
