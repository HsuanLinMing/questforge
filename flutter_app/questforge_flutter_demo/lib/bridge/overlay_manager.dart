// lib/bridge/overlay_manager.dart
import 'package:flutter/material.dart';
import 'package:questforge_ui_contract/questforge_contract.dart';

import '../debug/ask_reason_panel.dart';
import '../debug/confirm_quiz_panel.dart';
import '../debug/end_screen_overlay.dart';

class OverlayManagerV2 {
  const OverlayManagerV2();

  /// Overlay priority:
  /// 1) EndScreen
  /// 2) AskReason
  /// 3) ConfirmQuiz
  Widget? buildOverlay({
    required BuildContext context,

    // v2 commands
    required AskReasonCommandV2? ask,
    required ConfirmQuizCommandV2? quiz,
    required ShowEndScreenCommandV2? end,

    // ask
    required void Function(List<String> reasonIds, String text) onSubmitReasons,
    required VoidCallback onCloseAsk,

    // quiz
    required void Function(List<Object?> answers) onSubmitQuiz,
    required VoidCallback onCloseQuiz,

    // end (收斂)
    required ValueNotifier<bool> endLockVN,
    required ValueNotifier<String?> pendingEndVN,
    required void Function(UiActionSpecV2 action) onTapEndAction,
    required VoidCallback onCloseEnd,
  }) {
    if (end != null) {
      final raw = end.toJson();
      final actions = raw['actions'];
      final hasActions = actions is List && actions.isNotEmpty;

      // ✅ 沒有 actions 就不要蓋 EndScreen，讓 view 正常顯示 choices
      if (!hasActions) return null;
      return EndScreenOverlayV2(
        cmd: end,
        lockVN: endLockVN,
        pendingVN: pendingEndVN,
        onTapAction: onTapEndAction,
        onClose: onCloseEnd,
        showCloseButton: false,
      );
    }

    if (ask != null) {
      return AskReasonPanel(
        command: ask,
        onSubmit: (ids, text) => onSubmitReasons(ids, text),
        onClose: onCloseAsk,
      );
    }

    if (quiz != null) {
      return ConfirmQuizPanel(
        command: quiz,
        onSubmit: (answers) => onSubmitQuiz(answers),
        onClose: onCloseQuiz,
      );
    }

    return null;
  }
}
