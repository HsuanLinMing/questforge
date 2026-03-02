# QuestForge UI Color System
專案：霏霏樂樂小小偵探（QuestForge）
目的：統一 UI 色彩、按鈕與狀態顏色，讓 Flutter / 設計 / AI IDE 都能一致套用。

---

## 1. Brand Palette（品牌色）

### Primary（主色｜童趣亮藍｜偵探徽章感）
- Primary: #2F7BFF
- PrimaryDark: #1E4FD6
- PrimarySoft: #BFD7FF

使用建議：
- 主要 CTA 按鈕、重點 icon、連結、主要高亮
- Slider / Switch 打開狀態
- Loading / Progress

### Secondary（副色｜暖橘｜園遊會燈光）
- Secondary: #FFA43A
- SecondaryDark: #E07B00
- SecondarySoft: #FFE0B7

使用建議：
- 次要 CTA、獎勵、可愛提示（如「新故事」「驚喜」）
- Badge / Chip（暖色系）

### Accent（點綴色｜清爽綠｜成功/探索）
- Accent: #39D98A
- AccentDark: #1FAE66
- AccentSoft: #C9F5E1

使用建議：
- 成功提示、完成狀態、正向互動
- 第三層 CTA（如「設置」「更多」）

---

## 2. Surface & Background（背景/卡片）

- Background: #FFF8EE  （童書紙張感）
- Surface: #FFFFFF      （主要卡片）
- SurfaceAlt: #F3F7FF   （淡藍卡片/區塊）

- Border/Divider: #E6EAF2

使用建議：
- 頁面底：Background
- 卡片：Surface / SurfaceAlt
- 分隔線：Border/Divider

---

## 3. Text Colors（文字層級）

- TextPrimary: #1C2430
- TextSecondary: #5E6B7A
- TextTertiary: #92A0B2
- TextOnDark: #FFFFFF

使用建議：
- 標題：TextPrimary
- 內文/說明：TextSecondary
- 次要提示/Placeholder：TextTertiary

---

## 4. Feedback（狀態色）

- Success: #2ECC71
- Warning: #FFB020
- Error:   #FF4D4F
- Info:    #2F7BFF (同 Primary)

---

## 5. Buttons（按鈕規範）

### Primary Button（主要）
- Background: Primary (#2F7BFF)
- Pressed: PrimaryDark (#1E4FD6)
- Text/Icon: White (#FFFFFF)

### Secondary Button（次要）
- Background: Secondary (#FFA43A)
- Pressed: SecondaryDark (#E07B00)
- Text/Icon: White (#FFFFFF)

### Tertiary Button（第三）
- Background: Accent (#39D98A)
- Pressed: AccentDark (#1FAE66)
- Text/Icon: White (#FFFFFF)

### Disabled（禁用）
- Background: #E6EAF2
- Text: #92A0B2

---

## 6. Glass / Overlay Buttons（透明發亮按鈕，搭配你產的三色框框 PNG）

用途：放在背景圖上（主選單/故事背景），讓背景透出但按鈕仍清楚。

建議參數：
- Fill: brandColor with opacity 0.18
- Border: brandColor with opacity 0.65
- Highlight: white opacity 0.65
- Shadow: black opacity 0.12

示例：
- Glass Blue：Primary
- Glass Green：Accent
- Glass Orange：Secondary

---

## 7. Asset Naming（建議素材命名）
- Splash: assets/splash/questforge_splash.png
- Menu BG: assets/menu/questforge_main_menu.png
- Buttons:
  - assets/menu/btn_glass_blue.png
  - assets/menu/btn_glass_green.png
  - assets/menu/btn_glass_orange.png