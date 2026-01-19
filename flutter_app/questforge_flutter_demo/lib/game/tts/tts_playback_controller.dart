// lib/game/tts/tts_playback_controller.dart
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:questforge_flutter_demo/game/widgets/story_card_v2.dart';
import 'package:questforge_ui_contract/questforge_contract.dart';

typedef LogFn = void Function(String tag, Map<String, Object?> extra);
typedef ScrollToParagraphFn = void Function(int index);

class TtsPlaybackState {
  const TtsPlaybackState({
    required this.ready,
    required this.enabled,
    required this.playing,
    required this.activeParagraphIndex,
    required this.activeChunkIndex,
    required this.viewFp,
    required this.rate,
  });

  final bool ready;
  final bool enabled;
  final bool playing;
  final int activeParagraphIndex;
  final int activeChunkIndex;
  final String viewFp;

  /// ✅ 語速（FlutterTts speechRate）
  final double rate;

  TtsPlaybackState copyWith({
    bool? ready,
    bool? enabled,
    bool? playing,
    int? activeParagraphIndex,
    int? activeChunkIndex,
    String? viewFp,
    double? rate,
  }) {
    return TtsPlaybackState(
      ready: ready ?? this.ready,
      enabled: enabled ?? this.enabled,
      playing: playing ?? this.playing,
      activeParagraphIndex: activeParagraphIndex ?? this.activeParagraphIndex,
      activeChunkIndex: activeChunkIndex ?? this.activeChunkIndex,
      viewFp: viewFp ?? this.viewFp,
      rate: rate ?? this.rate,
    );
  }
}

///
/// TTS 播放控制器（macOS 友善）
/// - chunk + paragraph 連播
/// - progress handler 若不可靠，用 fallback timer（估算朗讀時間）補推進
/// - session/token guard：seek / view change / stop 都不會誤推進
///
class TtsPlaybackController {
  TtsPlaybackController({
    FlutterTts? tts,
    LogFn? logger,
  })  : _tts = tts ?? FlutterTts(),
        _logFn = logger;

  /// narration 播到「本 view 最後一段最後一 chunk」才觸發
  VoidCallback? onNarrationEnd;

  // ---------------------------
  // public
  // ---------------------------
  final ValueNotifier<TtsPlaybackState> vn = ValueNotifier<TtsPlaybackState>(
    const TtsPlaybackState(
      ready: false,
      enabled: true,
      playing: false,
      activeParagraphIndex: 0,
      activeChunkIndex: 0,
      viewFp: '',
      rate: 0.45,
    ),
  );

  bool get ready => vn.value.ready;
  bool get enabled => vn.value.enabled;
  bool get playing => vn.value.playing;
  int get activeParagraphIndex => vn.value.activeParagraphIndex;
  double get rate => vn.value.rate;

  void setEnabled(bool on) => vn.value = vn.value.copyWith(enabled: on);

  /// ✅ 外部設定語速（會立即套用到 TTS）
  Future<void> setRate(double r) async {
    final next = r.clamp(0.1, 1.0);
    vn.value = vn.value.copyWith(rate: next);
    try {
      await _tts.setSpeechRate(next);
    } catch (_) {}
  }

  // init once
  Future<void> init({
    String language = 'zh-TW',
    double speechRate = 0.45,
    double pitch = 1.0,
  }) async {
    // 以目前 state.rate 為主（讓外部可先 setRate 再 init 也行）
    final initRate = vn.value.rate;

    try {
      await _tts.setLanguage(language);
    } catch (_) {}
    try {
      await _tts.setSpeechRate(initRate == 0 ? speechRate : initRate);
      await _tts.setPitch(pitch);
    } catch (_) {}

    _tts.setProgressHandler((text, start, end, word) {
      if (_tokenSession != _playSession) return;
      if (text != _currentText) return;
      _currentProgressEnd = end;

      if (_currentLen > 0 && end >= _currentLen) {
        _triggerAdvance('progress_end');
      }
    });

    _tts.setCompletionHandler(() {
      _log('TTS_COMPLETE', {});
    });

    _tts.setCancelHandler(() {
      _log('TTS_CANCEL', {});
    });

    _tts.setErrorHandler((msg) {
      _log('TTS_ERROR', {'msg': msg});
      stop(resetToStart: false);
    });

    vn.value = vn.value.copyWith(ready: true);
  }

  Future<void> dispose() async {
    _fallbackTimer?.cancel();
    _fallbackTimer = null;
    try {
      await _tts.stop();
    } catch (_) {}
    vn.dispose();
  }

  Future<void> handleViewChanged({
    required NodeView view,
    required List<StoryParagraph> paragraphs,
    required String viewFp,
    required bool autoPlay,
    required ScrollToParagraphFn scrollTo,
  }) async {
    _scrollTo = scrollTo;

    _playSession++; // cut callbacks
    await stop(resetToStart: true);

    _playParagraphs = const <StoryParagraph>[];
    _playViewFp = '';

    if (!autoPlay) return;
    if (!enabled || !ready) return;
    if (paragraphs.isEmpty) return;

    if (_lastAutoPlayedFp == viewFp) return;
    _lastAutoPlayedFp = viewFp;

    await Future<void>.delayed(const Duration(milliseconds: 20));
    await playParagraph(
      index: 0,
      paragraphs: paragraphs,
      viewFp: viewFp,
      stopBeforeFirstChunk: true,
      deferUiUntilSpeak: false,
      scrollTo: scrollTo,
    );
  }

  Future<void> togglePlay({
    required List<StoryParagraph> paragraphs,
    required String viewFp,
    required ScrollToParagraphFn scrollTo,
  }) async {
    _scrollTo = scrollTo;

    if (!enabled) return;
    if (paragraphs.isEmpty) return;

    if (playing) {
      await stop(resetToStart: false);
      return;
    }

    final i = activeParagraphIndex.clamp(0, paragraphs.length - 1);
    await playParagraph(
      index: i,
      paragraphs: paragraphs,
      viewFp: viewFp,
      stopBeforeFirstChunk: true,
      deferUiUntilSpeak: false,
      scrollTo: scrollTo,
    );
  }

  Future<void> prev({
    required List<StoryParagraph> paragraphs,
    required String viewFp,
    required ScrollToParagraphFn scrollTo,
  }) async {
    await seekTo(
      index: activeParagraphIndex - 1,
      paragraphs: paragraphs,
      viewFp: viewFp,
      scrollTo: scrollTo,
    );
  }

  Future<void> next({
    required List<StoryParagraph> paragraphs,
    required String viewFp,
    required ScrollToParagraphFn scrollTo,
  }) async {
    await seekTo(
      index: activeParagraphIndex + 1,
      paragraphs: paragraphs,
      viewFp: viewFp,
      scrollTo: scrollTo,
    );
  }

  /// ✅ 重播目前段落（從頭播放）
  Future<void> replayCurrent({
    required List<StoryParagraph> paragraphs,
    required String viewFp,
    required ScrollToParagraphFn scrollTo,
  }) async {
    _scrollTo = scrollTo;

    if (!enabled) return;
    if (paragraphs.isEmpty) return;

    final idx = activeParagraphIndex.clamp(0, paragraphs.length - 1);

    _playSession++; // cut callbacks
    await stop(resetToStart: false);

    vn.value = vn.value.copyWith(
      activeParagraphIndex: idx,
      activeChunkIndex: 0,
    );
    scrollTo(idx);

    await playParagraph(
      index: idx,
      paragraphs: paragraphs,
      viewFp: viewFp,
      stopBeforeFirstChunk: true,
      deferUiUntilSpeak: false,
      scrollTo: scrollTo,
    );
  }

  Future<void> seekTo({
    required int index,
    required List<StoryParagraph> paragraphs,
    required String viewFp,
    required ScrollToParagraphFn scrollTo,
  }) async {
    _scrollTo = scrollTo;

    if (!enabled) return;
    if (paragraphs.isEmpty) return;

    final nextIndex = index.clamp(0, paragraphs.length - 1);
    final wasPlaying = playing;

    _playSession++; // cut callbacks
    await stop(resetToStart: false);

    vn.value = vn.value.copyWith(
      activeParagraphIndex: nextIndex,
      activeChunkIndex: 0,
    );
    scrollTo(nextIndex);

    if (wasPlaying) {
      await playParagraph(
        index: nextIndex,
        paragraphs: paragraphs,
        viewFp: viewFp,
        stopBeforeFirstChunk: true,
        deferUiUntilSpeak: false,
        scrollTo: scrollTo,
      );
    }
  }

  Future<void> stop({required bool resetToStart}) async {
    _fallbackTimer?.cancel();
    _fallbackTimer = null;

    _speakBusy = false;

    _speakToken++;
    _handledToken = -1;

    try {
      await _tts.stop();
    } catch (_) {}

    vn.value = vn.value.copyWith(
      playing: false,
      activeChunkIndex: 0,
      activeParagraphIndex: resetToStart ? 0 : vn.value.activeParagraphIndex,
      viewFp: vn.value.viewFp,
    );

    _ttsChunks = const <String>[];
    _currentText = '';
    _currentLen = 0;
    _currentProgressEnd = 0;
    _pendingActiveParagraphIndex = null;
  }

  // ---------------------------
  // internals
  // ---------------------------
  final FlutterTts _tts;
  final LogFn? _logFn;

  static const int _chunkMinChars = 12;
  static const int _chunkMaxChars = 28;

  List<StoryParagraph> _playParagraphs = const <StoryParagraph>[];
  String _playViewFp = '';

  ScrollToParagraphFn? _scrollTo;

  String _lastAutoPlayedFp = '';

  int _playSession = 0;

  int _speakToken = 0;
  int _handledToken = -1;
  int _tokenSession = 0;

  bool _speakBusy = false;
  bool _handlingAdvance = false;

  int? _pendingActiveParagraphIndex;

  List<String> _ttsChunks = const <String>[];

  String _currentText = '';
  String _currentSpeakText = '';
  int _currentLen = 0;
  int _currentProgressEnd = 0;
  DateTime? _speakStartedAt;
  Timer? _fallbackTimer;

  void _log(String tag, Map<String, Object?> extra) {
    _logFn?.call(tag, <String, Object?>{
      'play': vn.value.playing,
      'p': vn.value.activeParagraphIndex,
      'c': vn.value.activeChunkIndex,
      'sess': _playSession,
      'token': _speakToken,
      'handled': _handledToken,
      'viewFp': _playViewFp,
      'rate': vn.value.rate,
      ...extra,
    });
  }

  bool _isStrongPunc(String s) => s.contains(RegExp(r'[。！？!?]'));
  bool _isMidPunc(String s) => s.contains(RegExp(r'[，,、；;：:]'));
  bool _isAnyPunc(String s) => _isStrongPunc(s) || _isMidPunc(s) || s.contains('…');

  Duration _gapAfterChunk(String chunk) {
    if (_isStrongPunc(chunk)) return const Duration(milliseconds: 220);
    if (_isMidPunc(chunk) || chunk.contains('…')) return const Duration(milliseconds: 140);
    return const Duration(milliseconds: 70);
  }

  int _estimateSpeakMs(String text) {
    final t = text.trim();
    if (t.isEmpty) return 900;

    // 粗估：rate 越快，時間越短
    final r = vn.value.rate.clamp(0.2, 0.9);
    final rateFactor = (0.45 / r).clamp(0.6, 1.8);

    const int perChar = 190;

    final strong = RegExp(r'[。！？!?]').allMatches(t).length;
    final mid = RegExp(r'[，,、；;：:]').allMatches(t).length;
    final ellipsis = RegExp(r'…+').allMatches(t).length;

    var ms = (t.length * perChar * rateFactor).round();
    ms += (strong * 420 * rateFactor).round();
    ms += (mid * 220 * rateFactor).round();
    ms += (ellipsis * 320 * rateFactor).round();

    if (ms < 900) ms = 900;
    if (ms > 12000) ms = 12000;
    return ms;
  }

  void _armFallbackTimer({required int token, required String text}) {
    _fallbackTimer?.cancel();

    final expectMs = _estimateSpeakMs(text);

    _fallbackTimer = Timer(Duration(milliseconds: expectMs), () {
      if (_tokenSession != _playSession) return;
      if (token != _speakToken) return;
      if (_currentLen == 0) return;

      if (_currentProgressEnd >= _currentLen) return;

      final started = _speakStartedAt;
      if (started != null) {
        final elapsed = DateTime.now().difference(started).inMilliseconds;
        if (elapsed < expectMs) {
          final remain = (expectMs - elapsed).clamp(120, 3000);
          _fallbackTimer?.cancel();
          _fallbackTimer = Timer(Duration(milliseconds: remain), () {
            if (_tokenSession != _playSession) return;
            if (token != _speakToken) return;
            if (_currentLen == 0) return;
            if (_currentProgressEnd >= _currentLen) return;
            _triggerAdvance('fallback_timeout');
          });
          return;
        }
      }

      _triggerAdvance('fallback_timeout');
    });
  }

  void _triggerAdvance(String source) {
    if (!vn.value.playing) return;
    if (_tokenSession != _playSession) return;

    if (_handledToken == _speakToken) return;
    _handledToken = _speakToken;

    _fallbackTimer?.cancel();
    _fallbackTimer = null;

    if (_handlingAdvance) return;
    _handlingAdvance = true;

    _log('ADVANCE', {'by': source});

    Future.microtask(() async {
      try {
        if (_tokenSession != _playSession) return;
        await _advanceAfterChunkEnd();
      } finally {
        _handlingAdvance = false;
      }
    });
  }

  List<String> _splitByPunctuationKeeping(String text) {
    final t = text.trim();
    if (t.isEmpty) return const <String>[];

    final out = <String>[];
    final re = RegExp(r'[^。！？!?；;：:\n]+[。！？!?；;：:]?|…+|[\n]+');
    for (final m in re.allMatches(t)) {
      final s = m.group(0)?.trim() ?? '';
      if (s.isEmpty) continue;
      if (s == '\n') continue;
      out.add(s);
    }
    return out;
  }

  List<String> _splitLongByCommaOrFixed(String s) {
    final t = s.trim();
    if (t.length <= _chunkMaxChars) return <String>[t];

    final parts = t
        .split(RegExp(r'(?<=[，,、；;：:])'))
        .map((e) => e.trim())
        .where((e) => e.isNotEmpty)
        .toList();

    final out = <String>[];
    for (final p in (parts.isEmpty ? <String>[t] : parts)) {
      if (p.length <= _chunkMaxChars) {
        out.add(p);
      } else {
        var i = 0;
        while (i < p.length) {
          final end = (i + _chunkMaxChars).clamp(0, p.length);
          out.add(p.substring(i, end).trim());
          i = end;
        }
      }
    }
    return out.where((e) => e.isNotEmpty).toList();
  }

  List<String> _buildChunksForParagraph(String paragraphText) {
    final units = _splitByPunctuationKeeping(paragraphText);
    if (units.isEmpty) return const <String>[];

    final expanded = <String>[];
    for (final u in units) {
      if (u.length > _chunkMaxChars) {
        expanded.addAll(_splitLongByCommaOrFixed(u));
      } else {
        expanded.add(u);
      }
    }

    final out = <String>[];
    var buf = '';

    void flush() {
      final b = buf.trim();
      if (b.isNotEmpty) out.add(b);
      buf = '';
    }

    for (final piece in expanded) {
      final p = piece.trim();
      if (p.isEmpty) continue;

      if (buf.isEmpty) {
        buf = p;
        if (buf.length >= _chunkMinChars && _isAnyPunc(buf)) flush();
        continue;
      }

      final candidate = '$buf$p';
      if (candidate.length <= _chunkMaxChars) {
        buf = candidate;
        if (buf.length >= _chunkMinChars && _isAnyPunc(buf)) flush();
        continue;
      }

      flush();
      buf = p;
      if (buf.length >= _chunkMinChars && _isAnyPunc(buf)) flush();
    }

    flush();

    final merged = <String>[];
    for (final c in out) {
      if (merged.isNotEmpty && c.length <= 4) {
        merged[merged.length - 1] = '${merged.last}$c';
      } else {
        merged.add(c);
      }
    }
    return merged.where((e) => e.trim().isNotEmpty).toList();
  }

  Future<void> playParagraph({
    required int index,
    required List<StoryParagraph> paragraphs,
    required String viewFp,
    required bool stopBeforeFirstChunk,
    required bool deferUiUntilSpeak,
    required ScrollToParagraphFn scrollTo,
  }) async {
    if (!ready || !enabled) return;
    if (paragraphs.isEmpty) return;
    if (index < 0 || index >= paragraphs.length) return;

    _scrollTo = scrollTo;

    final text = paragraphs[index].text.trim();
    if (text.isEmpty) return;

    _playParagraphs = paragraphs;
    _playViewFp = viewFp;

    final chunks = _buildChunksForParagraph(text);
    if (chunks.isEmpty) return;

    vn.value = vn.value.copyWith(
      playing: true,
      viewFp: viewFp,
      activeChunkIndex: 0,
      activeParagraphIndex: deferUiUntilSpeak ? vn.value.activeParagraphIndex : index,
    );

    _ttsChunks = chunks;
    _pendingActiveParagraphIndex = deferUiUntilSpeak ? index : null;

    if (!deferUiUntilSpeak) {
      scrollTo(index);
    }

    await _speakCurrentChunk(
      stopBeforeSpeak: stopBeforeFirstChunk,
      scrollTo: scrollTo,
    );
  }

  Future<void> _speakCurrentChunk({
    required bool stopBeforeSpeak,
    required ScrollToParagraphFn scrollTo,
  }) async {
    if (!ready || !enabled) return;
    if (_ttsChunks.isEmpty) return;
    final ci = vn.value.activeChunkIndex;
    if (ci < 0 || ci >= _ttsChunks.length) return;
    if (_speakBusy) return;

    _speakBusy = true;

    final text = _ttsChunks[ci].trim();
    if (text.isEmpty) {
      _speakBusy = false;
      return;
    }

    _speakToken++;
    final token = _speakToken;
    _handledToken = -1;
    _tokenSession = _playSession;

    _currentText = text;
    _currentSpeakText = text;
    _currentLen = text.length;
    _currentProgressEnd = 0;
    _speakStartedAt = DateTime.now();

    _log('SPEAK', {
      'stop': stopBeforeSpeak,
      'token': token,
      'len': text.length,
      'text': text.length <= 30 ? text : '${text.substring(0, 30)}…',
    });

    try {
      if (stopBeforeSpeak) {
        _fallbackTimer?.cancel();
        _fallbackTimer = null;
        await _tts.stop();
      }

      final pending = _pendingActiveParagraphIndex;
      if (pending != null && ci == 0) {
        vn.value = vn.value.copyWith(activeParagraphIndex: pending);
        scrollTo(pending);
        _pendingActiveParagraphIndex = null;
      }

      _armFallbackTimer(token: token, text: _currentSpeakText);

      await _tts.speak(text);
    } catch (_) {
      // ignore
    } finally {
      _speakBusy = false;
    }
  }

  Future<void> _advanceAfterChunkEnd() async {
    if (!vn.value.playing) return;

    final scroll = _scrollTo ?? (_) {};

    final ci = vn.value.activeChunkIndex;
    if (_ttsChunks.isNotEmpty && ci >= 0 && ci < _ttsChunks.length) {
      final gap = _gapAfterChunk(_ttsChunks[ci]);
      if (gap.inMilliseconds > 0) {
        await Future<void>.delayed(gap);
      }
    }

    final nextChunk = vn.value.activeChunkIndex + 1;
    if (_ttsChunks.isNotEmpty && nextChunk < _ttsChunks.length) {
      vn.value = vn.value.copyWith(activeChunkIndex: nextChunk);
      await _speakCurrentChunk(stopBeforeSpeak: false, scrollTo: scroll);
      return;
    }

    if (_playParagraphs.isEmpty) {
      await stop(resetToStart: false);
      return;
    }

    var nextPara = vn.value.activeParagraphIndex + 1;
    while (nextPara < _playParagraphs.length && _playParagraphs[nextPara].text.trim().isEmpty) {
      nextPara++;
    }

    if (nextPara >= _playParagraphs.length) {
      final endSession = _playSession;
      await stop(resetToStart: false);

      if (endSession == _playSession) {
        onNarrationEnd?.call();
      }
      return;
    }

    await playParagraph(
      index: nextPara,
      paragraphs: _playParagraphs,
      viewFp: _playViewFp,
      stopBeforeFirstChunk: false,
      deferUiUntilSpeak: true,
      scrollTo: scroll,
    );
  }
}
