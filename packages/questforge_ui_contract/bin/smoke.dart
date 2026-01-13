import 'dart:convert';
import 'package:questforge_ui_contract/questforge_contract.dart';

void main() {
  final raw = {
    "type": "show_end_screen",
    "node_id": "ending_check",
    "tag": "ending_result",
    "title": "老師來幫忙",
    "narration": "霏霏牽著樂樂去找老師。",
    "lesson": ["先說看到的事實", "找大人幫忙"],
    "options": [
      {"id": "restart_case", "text": "再玩一次"}
    ],
    "meta": {
      "level": "ok",
      "score": 2,
      "threshold": 3,
      "reason_text": "我看到桌上有東西被拉過",
      "selected_observations": ["tape_was_pulled"]
    }
  };

  final cmd = SessionCommand.fromJson(raw);
  print(cmd.runtimeType);
  print(const JsonEncoder.withIndent('  ').convert(cmd.toJson()));
}
