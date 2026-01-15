// lib/game/ui_phase.dart
enum UiPhase {
  reading,   // 看故事（可滑、可點段落）
  choosing,  // 選項可按
  overlay,   // overlay 顯示中（全部鎖住）
  sending,   // 正在送 command（鎖選項/互動）
  ended,     // 已結束（顯示結局/不可再互動）
}

extension UiPhaseX on UiPhase {
  bool get allowStoryScroll => this == UiPhase.reading || this == UiPhase.choosing;
  bool get allowChoiceTap => this == UiPhase.choosing;
  bool get allowTopActions => this == UiPhase.reading || this == UiPhase.choosing; // 字體/播放等
  bool get blockAllTap => this == UiPhase.overlay || this == UiPhase.sending || this == UiPhase.ended;
}
