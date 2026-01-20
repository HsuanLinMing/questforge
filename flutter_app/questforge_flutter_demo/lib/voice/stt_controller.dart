// lib/game/voice/stt_controller.dart
import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;

@immutable
class SttState {
  final bool available; // initialize 是否成功
  final bool listening; // 目前是否正在聽
  final String recognizedText; // 最新辨識到的字
  final String status; // listening/notListening/done 等（plugin 回傳）
  final String error; // 錯誤訊息（若有）
  final String finalText; // 最後一次 final 結果（適合送出）

  const SttState({
    required this.available,
    required this.listening,
    required this.recognizedText,
    required this.finalText,
    required this.status,
    required this.error,
  });

  const SttState.initial()
      : available = false,
        listening = false,
        recognizedText = '',
        finalText = '',
        status = '',
        error = '';

  SttState copyWith({
    bool? available,
    bool? listening,
    String? recognizedText,
    String? finalText,
    String? status,
    String? error,
  }) {
    return SttState(
      available: available ?? this.available,
      listening: listening ?? this.listening,
      recognizedText: recognizedText ?? this.recognizedText,
      finalText: finalText ?? this.finalText,
      status: status ?? this.status,
      error: error ?? this.error,
    );
  }
}

class SttController {
  final stt.SpeechToText _stt = stt.SpeechToText();
  final ValueNotifier<SttState> vn = ValueNotifier<SttState>(const SttState.initial());

  bool _inited = false;

  String _preferredLocaleId = 'zh_TW';
  String? _activeLocaleId;

  int _epoch = 0;

  String _lastEmitted = '';
  DateTime _lastEmitAt = DateTime.fromMillisecondsSinceEpoch(0);

  // ✅ 把「沒聽到」視為非錯誤
  static const String _speechTimeoutMsg = 'error_speech_timeout';
  static const String _noMatchMsg = 'error_no_match';

  // ✅ Push-to-talk：給很長，避免 pause 自動停
  static const Duration _pttListenFor = Duration(minutes: 10);
  static const Duration _pttPauseFor = Duration(minutes: 10);

  // ✅ tap-to-talk（非按住）預設
  static const Duration _onceListenFor = Duration(seconds: 12);
  static const Duration _oncePauseFor = Duration(seconds: 2);

  Future<void> init({String preferredLocaleId = 'zh_TW'}) async {
    _preferredLocaleId = preferredLocaleId;
    if (_inited) return;
    _inited = true;

    try {
      final ok = await _stt.initialize(
        onStatus: _onStatus,
        onError: (e) {
          final msg = (e.errorMsg).toLowerCase();

          // ✅ timeout / no_match 都當作「沒聽到」
          if (msg == _speechTimeoutMsg) {
            vn.value = vn.value.copyWith(
              error: '',
              status: 'timeout',
              listening: false, // ✅ 統一收斂（避免 UI 卡在 listening）
            );
            return;
          }
          if (msg == _noMatchMsg) {
            vn.value = vn.value.copyWith(
              error: '',
              status: 'no_match',
              listening: false, // ✅ 統一收斂
            );
            return;
          }

          vn.value = vn.value.copyWith(error: e.errorMsg);
        },
      );

      vn.value = vn.value.copyWith(available: ok);
      if (!ok) return;

      try {
        final locales = await _stt.locales();
        _activeLocaleId = _pickLocale(locales, preferredLocaleId);
      } catch (_) {
        _activeLocaleId = preferredLocaleId;
      }
    } catch (e) {
      vn.value = vn.value.copyWith(available: false, error: e.toString());
    }
  }

  /// ✅ 點一下錄一段：等 final/done 自動停，回傳最後文字
  Future<String?> listenOnce({
    Duration listenFor = _onceListenFor,
    Duration pauseFor = _oncePauseFor,
    bool partialResults = true,
  }) async {
    final ok = await start(
      listenFor: listenFor,
      pauseFor: pauseFor,
      partialResults: partialResults,
      autoStopOnFinal: true,
    );
    if (!ok) return null;

    final myEpoch = _epoch;
    final completer = Completer<String?>();

    late VoidCallback sub;
    sub = () {
      final s = vn.value;
      if (_epoch != myEpoch) {
        vn.removeListener(sub);
        if (!completer.isCompleted) completer.complete(null);
        return;
      }
      if (!s.listening) {
        vn.removeListener(sub);
        final out = (s.finalText.isNotEmpty ? s.finalText : s.recognizedText).trim();
        completer.complete(out.isEmpty ? null : out);
      }
    };

    vn.addListener(sub);
    return completer.future;
  }

  /// ✅ 按住說話（push-to-talk）：你 UI 按下時呼叫 startHoldToTalk，放開呼叫 stop()
  Future<bool> startHoldToTalk({bool partialResults = true}) {
    return start(
      listenFor: _pttListenFor,
      pauseFor: _pttPauseFor,
      partialResults: partialResults,
      autoStopOnFinal: false,
    );
  }

  Future<bool> start({
    Duration listenFor = _onceListenFor,
    Duration pauseFor = _oncePauseFor,
    bool partialResults = true,
    bool autoStopOnFinal = false,
  }) async {
    if (!vn.value.available) return false;
    if (vn.value.listening) return true;

    _epoch++;
    final myEpoch = _epoch;

    _lastEmitted = '';
    _lastEmitAt = DateTime.fromMillisecondsSinceEpoch(0);

    vn.value = vn.value.copyWith(
      listening: true,
      recognizedText: '',
      finalText: '',
      error: '',
      status: 'listening',
    );

    try {
      await _stt.listen(
        localeId: _activeLocaleId ?? _preferredLocaleId,
        listenFor: listenFor,
        pauseFor: pauseFor,
        partialResults: partialResults,
        listenMode: stt.ListenMode.dictation,
        cancelOnError: false,
        onResult: (r) {
          if (_epoch != myEpoch) return;

          // ✅ stop 後 plugin 偶爾還會回來，直接忽略
          if (!vn.value.listening) return;

          final text = (r.recognizedWords).trim();
          if (text.isEmpty) return;

          final now = DateTime.now();
          final dt = now.difference(_lastEmitAt);
          final shouldEmit = (text != _lastEmitted) && (dt.inMilliseconds >= 120 || r.finalResult);
          if (!shouldEmit) return;

          _lastEmitted = text;
          _lastEmitAt = now;

          vn.value = vn.value.copyWith(
            recognizedText: text,
            finalText: r.finalResult ? text : vn.value.finalText,
          );

          if (autoStopOnFinal && r.finalResult) {
            unawaited(stop());
          }
        },
      );
      return true;
    } catch (e) {
      vn.value = vn.value.copyWith(listening: false, error: e.toString());
      return false;
    }
  }

  Future<void> stop() async {
    if (!vn.value.listening) return;
    final myEpoch = _epoch;

    // ✅ 先收斂 UI（避免放開後還顯示 listening）
    vn.value = vn.value.copyWith(listening: false, status: 'stopping');

    try {
      await _stt.stop();
    } catch (_) {}

    // 有些平台 stop 後不一定馬上觸發 status
    if (_epoch == myEpoch) {
      vn.value = vn.value.copyWith(listening: false);
    }
  }

  Future<void> cancel() async {
    if (!vn.value.listening) return;
    final myEpoch = _epoch;

    vn.value = vn.value.copyWith(listening: false, status: 'cancel');

    try {
      await _stt.cancel();
    } catch (_) {}

    if (_epoch == myEpoch) {
      vn.value = vn.value.copyWith(listening: false);
    }
  }

  void _onStatus(String s) {
    vn.value = vn.value.copyWith(status: s);

    final lower = s.toLowerCase();
    final done = lower.contains('done') || lower.contains('notlistening');

    if (vn.value.listening && done) {
      vn.value = vn.value.copyWith(listening: false);
    }
  }

  String _pickLocale(List<stt.LocaleName> locales, String preferred) {
    for (final l in locales) {
      if (l.localeId == preferred) return l.localeId;
    }

    final prefLower = preferred.toLowerCase();
    final prefPrefix = prefLower.split(RegExp(r'[_-]')).first;

    for (final l in locales) {
      final id = l.localeId.toLowerCase();
      if (id == prefLower) return l.localeId;
      if (id.startsWith(prefPrefix)) return l.localeId;
    }

    for (final l in locales) {
      final id = l.localeId.toLowerCase();
      if (id.contains('zh') && (id.contains('tw') || id.contains('hant'))) return l.localeId;
    }

    return locales.isNotEmpty ? locales.first.localeId : preferred;
  }

  void dispose() {
    vn.dispose();
  }
}
