// lib/dev/bridge/bridge_sender.dart
import 'package:questforge_flutter_demo/dev/python_bridge.dart';

class BridgeSender {
  BridgeSender(this._bridge);

  final PythonBridge _bridge;

  void sendChoose(int choiceIndex) {
    _bridge.send(<String, dynamic>{
      'type': 'choose',
      'choice_index': choiceIndex, // ✅ 對齊 python: choice_index
    });
  }

  void sendReplay() {
    _bridge.send(<String, dynamic>{'type': 'replay'});
  }

  void sendSetReasons({
    required List<String> reasonIds,
    required String text,
  }) {
    _bridge.send(<String, dynamic>{
      'type': 'set_reasons',
      'reason_ids': reasonIds, // ✅ 對齊 python: reason_ids
      'reason_text': text, // ✅ 對齊 python: reason_text
    });
  }

  void sendConfirmQuizAnswerList(
    List<Object?> answers, {
    bool skipped = false,
  }) {
    _bridge.send(<String, dynamic>{
      'type': 'confirm_quiz_answer',
      'answers': answers,
      if (skipped) 'skipped': true,
    });
  }

  /// ✅ 對齊 python：ui_action 是 envelope + payload
  /// python: {'type':'ui_action','payload':{kind,id,action,data}}
  void sendUiAction({
    required String kind,
    required String id,
    Map<String, dynamic>? data,
  }) {
    _bridge.send(<String, dynamic>{
      'type': 'ui_action',
      'payload': <String, dynamic>{
        'kind': kind,
        'id': id,
        'action': id, // ✅ 你 python 端通常也會看 action
        if (data != null) 'data': data,
      },
    });
  }
}
