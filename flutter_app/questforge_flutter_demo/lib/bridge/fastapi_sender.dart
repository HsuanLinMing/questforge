// lib/bridge/fastapi_sender.dart
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:questforge_flutter_demo/fastapi_bridge.dart';

typedef SenderOnStep = void Function(
  GameStepResp r, {
  required String type,
  Map<String, dynamic>? extra,
});

typedef SenderOnError = void Function(
  Object e,
  StackTrace st, {
  required String type,
  Map<String, dynamic>? extra,
});

/// 給 OverlayManagerV2 用：
/// - sendChoose / sendReplay / sendUiAction(end_flow) / sendSetReasons / sendConfirmQuizAnswerList
/// - 由 controller 注入 onStep/onError，sender 打完 API 後回寫 UI
class BridgeSenderApi {
  BridgeSenderApi(
    this._api, {
    required SenderOnStep onStep,
    required SenderOnError onError,
  })  : _onStep = onStep,
        _onError = onError;

  final FastApiBridge _api;
  final SenderOnStep _onStep;
  final SenderOnError _onError;

  void sendChoose(int index) {
    unawaited(() async {
      try {
        final r = await _api.choose(choiceIndex: index);
        _onStep(
          r,
          type: 'api_choose(sender)',
          extra: <String, dynamic>{'choice_index': index},
        );
      } catch (e, st) {
        _onError(
          e,
          st,
          type: 'api_choose(sender)',
          extra: <String, dynamic>{'choice_index': index},
        );
      }
    }());
  }

  void sendReplay() {
    unawaited(() async {
      try {
        final r = await _api.replay();
        _onStep(r, type: 'api_replay(sender)');
      } catch (e, st) {
        _onError(e, st, type: 'api_replay(sender)');
      }
    }());
  }

  void sendNext() {
    unawaited(() async {
      try {
        final r = await _api.next();
        _onStep(r, type: 'api_next(sender)');
      } catch (e, st) {
        _onError(e, st, type: 'api_next(sender)');
      }
    }());
  }

  void sendJump(String targetNodeId) {
    unawaited(() async {
      try {
        final r = await _api.jump(targetNodeId: targetNodeId);
        _onStep(
          r,
          type: 'api_jump(sender)',
          extra: <String, dynamic>{'target_node_id': targetNodeId},
        );
      } catch (e, st) {
        _onError(
          e,
          st,
          type: 'api_jump(sender)',
          extra: <String, dynamic>{'target_node_id': targetNodeId},
        );
      }
    }());
  }

  /// Overlay EndScreen 用：kind='end_flow'，id=end_action
  void sendUiAction({
    required String kind,
    required String id,
    Map<String, dynamic>? data,
  }) {
    if (kind != 'end_flow') {
      debugPrint('[BridgeSenderApi] ignore ui_action kind=$kind id=$id');
      return;
    }

    unawaited(() async {
      try {
        final r = await _api.endFlow(endAction: id);
        _onStep(
          r,
          type: 'api_end_flow(sender)',
          extra: <String, dynamic>{'end_action': id},
        );
      } catch (e, st) {
        _onError(
          e,
          st,
          type: 'api_end_flow(sender)',
          extra: <String, dynamic>{'end_action': id},
        );
      }
    }());
  }

  void sendSetReasons({
    required List<String> reasonIds,
    String? text,
  }) {
    unawaited(() async {
      try {
        final r = await _api.setReasons(
          reasonIds: reasonIds,
          reasonText: text ?? '',
        );
        _onStep(
          r,
          type: 'api_set_reasons(sender)',
          extra: <String, dynamic>{
            'reason_ids': reasonIds,
            'reason_text': text ?? '',
          },
        );
      } catch (e, st) {
        _onError(
          e,
          st,
          type: 'api_set_reasons(sender)',
          extra: <String, dynamic>{'reason_ids': reasonIds},
        );
      }
    }());
  }

  void sendConfirmQuizAnswerList(
    List<Object?> answers, {
    bool skipped = false,
  }) {
    unawaited(() async {
      try {
        final r = await _api.confirmQuiz(
          answers: answers,
          skipped: skipped,
        );
        _onStep(
          r,
          type: 'api_confirm_quiz(sender)',
          extra: <String, dynamic>{
            'answers': answers,
            'skipped': skipped,
          },
        );
      } catch (e, st) {
        _onError(
          e,
          st,
          type: 'api_confirm_quiz(sender)',
          extra: <String, dynamic>{'skipped': skipped},
        );
      }
    }());
  }
}
