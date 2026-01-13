import 'package:questforge_ui_contract/src/v2/ask_reason_command_v2.dart';
import 'package:questforge_ui_contract/src/v2/confirm_quiz_command_v2.dart';

import 'command_base_v2.dart';
import 'show_end_screen_command_v2.dart';

class CommandParserV2 {
  static CommandV2? tryFromJson(Map<String, dynamic> json) {
    final t = (json['type'] ?? '').toString();
    switch (t) {
      case 'show_end_screen':
        return ShowEndScreenCommandV2.fromJson(json);
      case 'ask_reason':
        return AskReasonCommandV2.fromJson(json);
      case 'confirm_quiz':
  return ConfirmQuizCommandV2.fromJson(json);
      default:
        return null;
    }
  }
}
