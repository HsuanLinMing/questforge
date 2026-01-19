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

  /// 最後一次「final」結果（更適合拿來送出）
  final String finalText;

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

  /// 使用者偏好 locale（若找不到會 fallback）
  String _preferredLocaleId = 'zh_TW';

  /// initialize 後選到的實際 locale（保證存在於 locales）
  String? _activeLocaleId;

  /// 避免同時多次 start/stop 的競態
  int _epoch = 0;

  /// partial 會一直抖動：做個小 debounce / 去重
  String _lastEmitted = '';
  DateTime _lastEmitAt = DateTime.fromMillisecondsSinceEpoch(0);

  /// 有些平台 onStatus 會先來 notListening 再來 done
  bool _sawDoneOrNotListening = false;

  /// ✅ (B) 把 speech_timeout 當「沒聽到」，不要當錯誤
  static const String _speechTimeoutMsg = 'error_speech_timeout';

  /// ✅ (C) 把 no_match 當「沒聽到」，不要當錯誤
  static const String _noMatchMsg = 'error_no_match';

  /// ✅ (PTT) push-to-talk 預設：很長，避免停頓就自動停止
  static const Duration _pttListenFor = Duration(minutes: 10);
  static const Duration _pttPauseFor = Duration(minutes: 10);

  Future<void> init({String preferredLocaleId = 'zh_TW'}) async {
    _preferredLocaleId = preferredLocaleId;
    if (_inited) return;
    _inited = true;

    try {
      final ok = await _stt.initialize(
        onStatus: _onStatus,
        onError: (e) {
          final msg = (e.errorMsg).toLowerCase();

          // ✅ timeout 不算錯誤
          if (msg == _speechTimeoutMsg) {
            vn.value = vn.value.copyWith(
              error: '',
              status: 'timeout',
              listening: false,
            );
            return;
          }

          // ✅ no_match 不算錯誤（沒聽到就算了）
          if (msg == _noMatchMsg) {
            vn.value = vn.value.copyWith(
              error: '',
              status: 'no_match',
              // 不強制把 listening=false，交給 onStatus/stop 統一收斂
            );
            return;
          }

          vn.value = vn.value.copyWith(error: e.errorMsg);
        },
      );

      vn.value = vn.value.copyWith(available: ok);
      if (!ok) return;

      // ✅ C: 盡量選到「真的存在」的 locale，否則 fallback
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

  /// 最適合你的 accuse：按一下開始聽，等 final/done 自動停，回傳最後文字
  Future<String?> listenOnce({
    // ✅ A: 預設拉長（孩子開口比較慢）
    Duration listenFor = _pttListenFor,
    Duration pauseFor = _pttPauseFor,
    bool partialResults = true,
  }) async {
    final ok = await start(
      listenFor: listenFor,
      pauseFor: pauseFor,
      partialResults: partialResults,
      autoStopOnFinal: true,
    );
    if (!ok) return null;

    // 等到 listening 結束（status done / notListening / stop 被呼叫）
    final myEpoch = _epoch;
    final completer = Completer<String?>();

    late VoidCallback sub;
    sub = () {
      final s = vn.value;
      if (_epoch != myEpoch) {
        // 被下一次 start 覆蓋
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

  Future<bool> start({
    // ✅ A: 預設拉長，避免一按就 timeout
    Duration listenFor = const Duration(seconds: 12),
    Duration pauseFor = const Duration(seconds: 2),
    bool partialResults = true,
    bool autoStopOnFinal = false,
  }) async {
    if (!vn.value.available) return false;
    if (vn.value.listening) return true;

    _epoch++;
    final myEpoch = _epoch;

    _sawDoneOrNotListening = false;
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

        // ✅ A: dictation 模式更適合講一句話
        listenMode: stt.ListenMode.dictation,

        // ✅ A: 避免一個小 error 就直接把流程炸掉（仍會走 onError）
        cancelOnError: false,

        onResult: (r) {
          if (_epoch != myEpoch) return;

          final text = (r.recognizedWords).trim();

          // partial 抖動很頻繁，做去重 + 最小間隔
          final now = DateTime.now();
          final dt = now.difference(_lastEmitAt);
          final shouldEmit = text.isNotEmpty && (text != _lastEmitted) && (dt.inMilliseconds >= 120 || r.finalResult);

          if (!shouldEmit) return;

          _lastEmitted = text;
          _lastEmitAt = now;

          vn.value = vn.value.copyWith(
            recognizedText: text,
            finalText: r.finalResult ? text : vn.value.finalText,
          );

          if (autoStopOnFinal && r.finalResult) {
            // 有些平台 finalResult 出來後不一定立刻 onStatus done
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

  /// ✅ Push-to-talk 專用：只要按住開始就呼叫這個
  Future<bool> startHoldToTalk({bool partialResults = true}) {
    return start(
      listenFor: _pttListenFor,
      pauseFor: _pttPauseFor,
      partialResults: partialResults,
      autoStopOnFinal: false, // ✅ 不因 final 自停
    );
  }

  Future<void> stop() async {
    if (!vn.value.listening) return;
    final myEpoch = _epoch;

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

    try {
      await _stt.cancel();
    } catch (_) {}

    if (_epoch == myEpoch) {
      vn.value = vn.value.copyWith(listening: false);
    }
  }

  void _onStatus(String s) {
    vn.value = vn.value.copyWith(status: s);

    // plugin 的 status 很多種：
    // - listening
    // - notListening
    // - done
    // 我們只要看到 notListening/done，就把 listening 收斂掉
    final lower = s.toLowerCase();
    final done = lower.contains('done') || lower.contains('notlistening');

    if (done) _sawDoneOrNotListening = true;

    if (vn.value.listening && done) {
      vn.value = vn.value.copyWith(listening: false);
    }
  }

  String _pickLocale(List<stt.LocaleName> locales, String preferred) {
    // 1) 完全 match
    for (final l in locales) {
      if (l.localeId == preferred) return l.localeId;
    }

    // 2) match 語系前綴（zh / zh_TW / zh-Hant 類）
    final prefLower = preferred.toLowerCase();
    final prefPrefix = prefLower.split(RegExp(r'[_-]')).first;
    for (final l in locales) {
      final id = l.localeId.toLowerCase();
      if (id == prefLower) return l.localeId;
      if (id.startsWith(prefPrefix)) return l.localeId;
    }

    // 3) 嘗試找繁中
    for (final l in locales) {
      final id = l.localeId.toLowerCase();
      if (id.contains('zh') && (id.contains('tw') || id.contains('hant'))) return l.localeId;
    }

    // 4) fallback 第一個（或 preferred）
    return locales.isNotEmpty ? locales.first.localeId : preferred;
  }

  void dispose() {
    vn.dispose();
  }
}
