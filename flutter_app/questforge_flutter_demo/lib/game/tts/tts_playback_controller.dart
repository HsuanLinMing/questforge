// lib/game/tts/tts_playback_controller.dart
import 'dart:async';
import 'dart:convert'; // ✅ utf8
import 'package:crypto/crypto.dart'; // ✅ sha1

import 'package:flutter/foundation.dart';
import 'package:just_audio/just_audio.dart';
import 'package:questforge_flutter_demo/game/widgets/story_card_v2.dart';
import 'package:questforge_flutter_demo/fastapi_bridge.dart';
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
    required this.didSpeak,
    required this.didSpeakFp,
    required this.activeRole,
    required this.activeVoice,
  });

  final bool ready;
  final bool enabled;
  final bool playing;
  final int activeParagraphIndex;
  final int activeChunkIndex;
  final String viewFp;

  /// ✅ 播放倍速（just_audio speed）
  final double rate;

  /// ✅ 這一輪 view 真的有開始播音檔嗎？（避免 playlist missing 時觸發 onNarrationEnd → autoContinue）
  final bool didSpeak;

  /// ✅ 哪個 viewFp 曾經真的播過（debug 用）
  final String didSpeakFp;
  final String activeRole;
  final String activeVoice;

  TtsPlaybackState copyWith({
    bool? ready,
    bool? enabled,
    bool? playing,
    int? activeParagraphIndex,
    int? activeChunkIndex,
    String? viewFp,
    double? rate,
    bool? didSpeak,
    String? didSpeakFp,
    String? activeRole,
    String? activeVoice,
  }) {
    return TtsPlaybackState(
      ready: ready ?? this.ready,
      enabled: enabled ?? this.enabled,
      playing: playing ?? this.playing,
      activeParagraphIndex: activeParagraphIndex ?? this.activeParagraphIndex,
      activeChunkIndex: activeChunkIndex ?? this.activeChunkIndex,
      viewFp: viewFp ?? this.viewFp,
      rate: rate ?? this.rate,
      didSpeak: didSpeak ?? this.didSpeak,
      didSpeakFp: didSpeakFp ?? this.didSpeakFp,
      activeRole: activeRole ?? this.activeRole,
      activeVoice: activeVoice ?? this.activeVoice,
    );
  }
}

// -----------------------------------------------------------------------------
// Playlist v1 (from python command: type=tts_playlist_v1)
// -----------------------------------------------------------------------------
class _TtsPlaylistItem {
  _TtsPlaylistItem({
    required this.index,
    required this.path,
    required this.role,
    required this.voice,
    required this.text,
    required this.format,
    required this.ready,
  });

  final int index; // paragraph index
  final String path; // file://... or http(s)://...
  final String role;
  final String voice;
  final String text;
  final String format;
  final bool ready;

  static _TtsPlaylistItem? tryFromMap(Map<String, dynamic> m) {
    final raw = (m['path'] ?? m['url'] ?? m['href'] ?? '').toString().trim();
    if (raw.isEmpty) return null;

    final idxRaw = m['index'];
    final idx = (idxRaw is int) ? idxRaw : int.tryParse('$idxRaw') ?? 0;
    final text =
        (m['text'] ?? m['narration'] ?? m['content'] ?? m['subtitle'] ?? '')
            .toString();

    return _TtsPlaylistItem(
      index: idx,
      path: raw,
      role: '${m['role'] ?? ''}',
      voice: '${m['voice'] ?? ''}',
      text: text,
      format: '${m['format'] ?? ''}',
      ready: (m['ready'] == true),
    );
  }
}

class _TtsPlaylistV1 {
  _TtsPlaylistV1({
    required this.scope,
    required this.viewFp,
    required this.uiViewFp,
    required this.totalCount,
    required this.status,
    required this.reason,
    required this.items,
  });

  final String scope; // view/end
  final String viewFp; // ✅ 後端 pool path key（sha1）
  final String uiViewFp; // ✅ 後端回傳的 ui_view_fp（可與 viewFp 相同）
  final int totalCount; // ✅ 這頁總共有幾段 (用來給前端輪詢等待用)
  final String status; // ok/unavailable/empty_narration/error
  final String reason;
  final List<_TtsPlaylistItem> items;

  bool get playable => status == 'ok' && items.isNotEmpty;

  static _TtsPlaylistV1 fromCommand(Map<String, dynamic> cmd) {
    final itemsRaw = cmd['items'];
    final items = <_TtsPlaylistItem>[];
    if (itemsRaw is List) {
      for (final x in itemsRaw) {
        if (x is Map) {
          final it = _TtsPlaylistItem.tryFromMap(x.cast<String, dynamic>());
          if (it != null) items.add(it);
        }
      }
    }

    // ✅ 強制按 index 排序（止血：避免後端 items 順序亂）
    items.sort((a, b) => a.index.compareTo(b.index));

    return _TtsPlaylistV1(
      scope: '${cmd['scope'] ?? 'view'}',
      viewFp: '${cmd['view_fp'] ?? ''}',
      uiViewFp: '${cmd['ui_view_fp'] ?? ''}',
      totalCount: (cmd['total_count'] is int)
          ? (cmd['total_count'] as int)
          : items.length,
      status: '${cmd['status'] ?? 'ok'}',
      reason: '${cmd['reason'] ?? ''}',
      items: items,
    );
  }
}

///
/// TTS 播放控制器（播放 Python 回來的音檔 playlist）
/// - activeChunkIndex：playlist item cursor 進度（不是文字 chunk）
/// - activeParagraphIndex：目前播放到哪一段（用 item.index）
/// - rate：音檔播放倍速
///
class TtsPlaybackController {
  TtsPlaybackController({
    LogFn? logger,
  }) : _logFn = logger;

  /// narration 播放到「playlist 最後一個 item」才觸發
  /// ✅ 注意：只有 didSpeak==true 才會觸發（避免 playlist missing 時 autoContinue）
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
      rate: 1.0,
      didSpeak: false,
      didSpeakFp: '',
      activeRole: '',
      activeVoice: '',
    ),
  );

  bool get ready => vn.value.ready;
  bool get enabled => vn.value.enabled;
  bool get playing => vn.value.playing;
  int get activeParagraphIndex => vn.value.activeParagraphIndex;
  double get rate => vn.value.rate;

  void setEnabled(bool on) => vn.value = vn.value.copyWith(enabled: on);

  /// ✅ 外部設定倍速（just_audio speed）
  Future<void> setRate(double r) async {
    final next = r.clamp(0.6, 1.4);
    vn.value = vn.value.copyWith(rate: next);
    try {
      await _player.setSpeed(next);
    } catch (_) {}
  }

  void init() {
    if (_inited) return;
    _inited = true;

    vn.value = vn.value.copyWith(ready: true);

    _player.setSpeed(vn.value.rate).catchError((_) {});

    _stateSub?.cancel();
    _stateSub = _player.playerStateStream.listen((st) {
      if (_tokenSession != _playSession) return;
      if (st.processingState == ProcessingState.completed) {
        _triggerAdvance('audio_completed');
      }
    });
  }

  Future<void> dispose() async {
    _fallbackTimer?.cancel();
    _fallbackTimer = null;

    await _stateSub?.cancel();
    _stateSub = null;

    try {
      await _player.stop();
    } catch (_) {}

    vn.dispose();
  }

  // ---------------------------------------------------------------------------
  // view fingerprint (align with backend)
  // ---------------------------------------------------------------------------
  String _computeUiViewFpFromNarration(String narration) {
    // backend: sha1("v2|"+narration)
    final n = (narration).toString();
    final bytes = utf8.encode('v2|$n');
    return sha1.convert(bytes).toString();
  }

  // ---------------------------------------------------------------------------
  // view changed integration
  // ---------------------------------------------------------------------------
  Future<void> handleViewChanged({
    required NodeView view,
    required List<StoryParagraph> paragraphs,
    required String viewFp, // 你外部算的 fp（現在不用它當真相，只當 fallback）
    required bool autoPlay,
    required ScrollToParagraphFn scrollTo,
    required Map<String, dynamic>? playlistCmd,
    Future<Map<String, dynamic>?> Function()? fetchPlaylistCmd,
    Future<TtsStatus> Function({required String viewFp, required int count})?
        fetchTtsStatus,
  }) async {
    _scrollTo = scrollTo;
    _fetchTtsStatus = fetchTtsStatus;

    _playSession++; // cut callbacks
    await stop(resetToStart: true);

    _playParagraphs = const <StoryParagraph>[];
    _playViewFp = '';
    _playlist = null;
    _playlistCursor = 0;

    _fetchPlaylistCmd = fetchPlaylistCmd;

    // ✅ reset didSpeak for this view
    vn.value = vn.value.copyWith(didSpeak: false, didSpeakFp: '');

    _playParagraphs = paragraphs;

    final narration = (view.narration ?? '').toString();
    final uiFp = narration.trim().isEmpty
        ? viewFp
        : _computeUiViewFpFromNarration(narration);

    // ✅ 先把目前 view 的 fp 設成「對齊後端的 fp」
    _playViewFp = uiFp;
    vn.value = vn.value.copyWith(viewFp: uiFp);

    final pl =
        (playlistCmd == null) ? null : _TtsPlaylistV1.fromCommand(playlistCmd);

    // ✅ 嚴謹：如果後端有給 view_fp，就必須 match 我們算出來的 uiFp（避免亂播）
    // 💡 修正：如果算出來不一致，我們只印警告，不要直接拋棄 playlist，因為有時 narration 字串在 flutter / python 會有些微差異
    final plFp = (pl?.viewFp ?? '').trim();
    if (pl != null && plFp.isNotEmpty && plFp != uiFp.trim()) {
      _log('PLAYLIST_FP_MISMATCH_WARNING', {
        'pl_viewFp': plFp,
        'ui_viewFp': uiFp.trim(),
        'status': pl.status,
        'items': pl.items.length,
        'note':
            'Flutter fp aligned to sha1("v2|narration") but mismatched. Continuing anyway.',
      });
      // 以前這會 return 導致沒有聲音，現在放行
      // _playlist = null;
      // return;
    }

    _playlist = pl;

    if (!autoPlay) return;
    if (!enabled || !ready) return;
    if (paragraphs.isEmpty) return;

    // ✅ dedupe：用 uiFp（對齊後端）做去重
    if (_lastAutoPlayedFp == uiFp) return;
    _lastAutoPlayedFp = uiFp;

    // ✅ playlist 不可播：只 log，不要 onNarrationEnd（避免直接 autoContinue）
    if (pl == null || !pl.playable) {
      _log('PLAYLIST_UNAVAILABLE', {
        'status': pl?.status ?? 'missing',
        'reason': pl?.reason ?? '',
        'ui_viewFp': uiFp,
      });
      return;
    }

    await Future<void>.delayed(const Duration(milliseconds: 20));
    await playParagraph(
      index: 0,
      paragraphs: paragraphs,
      viewFp: uiFp, // ✅ 用對齊後端的 fp
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

    final pl = _playlist;
    if (pl == null || !pl.playable) {
      _log('TOGGLE_NO_AUDIO', {'reason': pl == null ? 'missing' : pl.status});
      return; // ✅ 不要 onNarrationEnd
    }

    if (playing) {
      await stop(resetToStart: false);
      return;
    }

    final i = activeParagraphIndex.clamp(0, paragraphs.length - 1);
    await playParagraph(
      index: i,
      paragraphs: paragraphs,
      viewFp: _playViewFp.isNotEmpty ? _playViewFp : viewFp,
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
      viewFp: _playViewFp.isNotEmpty ? _playViewFp : viewFp,
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
      viewFp: _playViewFp.isNotEmpty ? _playViewFp : viewFp,
      scrollTo: scrollTo,
    );
  }

  Future<void> replayCurrent({
    required List<StoryParagraph> paragraphs,
    required String viewFp,
    required ScrollToParagraphFn scrollTo,
  }) async {
    _scrollTo = scrollTo;

    if (!enabled) return;
    if (paragraphs.isEmpty) return;

    final pl = _playlist;
    if (pl == null || !pl.playable) return;

    final idx = activeParagraphIndex.clamp(0, paragraphs.length - 1);

    _playSession++;
    await stop(resetToStart: false);

    vn.value = vn.value.copyWith(
      activeParagraphIndex: idx,
      activeChunkIndex: 0,
    );
    scrollTo(idx);

    await playParagraph(
      index: idx,
      paragraphs: paragraphs,
      viewFp: _playViewFp.isNotEmpty ? _playViewFp : viewFp,
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

    final pl = _playlist;
    final nextIndex = index.clamp(0, paragraphs.length - 1);

    if (pl == null || !pl.playable) {
      vn.value = vn.value
          .copyWith(activeParagraphIndex: nextIndex, activeChunkIndex: 0);
      scrollTo(nextIndex);
      return;
    }

    final wasPlaying = playing;

    _playSession++;
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
        viewFp: _playViewFp.isNotEmpty ? _playViewFp : viewFp,
        stopBeforeFirstChunk: true,
        deferUiUntilSpeak: false,
        scrollTo: scrollTo,
      );
    }
  }

  Future<void> stop({required bool resetToStart}) async {
    _fallbackTimer?.cancel();
    _fallbackTimer = null;

    _handlingAdvance = false;

    _speakToken++;
    _handledToken = -1;

    try {
      await _player.stop();
    } catch (_) {}

    vn.value = vn.value.copyWith(
      playing: false,
      activeChunkIndex: 0,
      activeParagraphIndex: resetToStart ? 0 : vn.value.activeParagraphIndex,
    );

    _pendingActiveParagraphIndex = null;
  }

  // ---------------------------
  // internals
  // ---------------------------
  final LogFn? _logFn;

  // ✅ Share a single AudioPlayer instance to avoid race condition where
  // the old controller's dispose() deactivates the AudioSession while the new one is playing
  static final AudioPlayer _sharedPlayer = AudioPlayer();
  AudioPlayer get _player => _sharedPlayer;

  StreamSubscription<PlayerState>? _stateSub;

  bool _inited = false;

  List<StoryParagraph> _playParagraphs = const <StoryParagraph>[];
  String _playViewFp = '';

  ScrollToParagraphFn? _scrollTo;

  String _lastAutoPlayedFp = '';

  int _playSession = 0;

  int _speakToken = 0;
  int _handledToken = -1;
  int _tokenSession = 0;

  bool _handlingAdvance = false;

  int? _pendingActiveParagraphIndex;

  _TtsPlaylistV1? _playlist;
  int _playlistCursor = 0;

  Timer? _fallbackTimer;

  Future<Map<String, dynamic>?> Function()? _fetchPlaylistCmd;
  Future<TtsStatus> Function({required String viewFp, required int count})?
      _fetchTtsStatus;

  Future<void> _refreshPlaylistIfPossible() async {
    final fetch = _fetchPlaylistCmd;
    if (fetch == null) return;
    try {
      final raw = await fetch();
      if (raw == null) return;

      // If view already changed, ignore.
      if (_tokenSession != _playSession) return;

      final next = _TtsPlaylistV1.fromCommand(raw);
      if (!next.playable) return;

      // Keep cursor roughly aligned by paragraph index.
      final cur = _playlist;
      final curIdx = (cur != null &&
              _playlistCursor >= 0 &&
              _playlistCursor < cur.items.length)
          ? cur.items[_playlistCursor].index
          : vn.value.activeParagraphIndex;

      _playlist = next;
      _playlistCursor = _firstCursorForParagraph(curIdx);

      _log('PLAYLIST_REFRESHED', {
        'items': next.items.length,
        'cursor': _playlistCursor,
        'pIndex': curIdx,
        'status': next.status,
      });
    } catch (e) {
      _log('PLAYLIST_REFRESH_FAILED', {'err': e.toString()});
    }
  }

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
      'didSpeak': vn.value.didSpeak,
      'didSpeakFp': vn.value.didSpeakFp,
      ...extra,
    });
  }

  Duration _estimateAudioTimeout(_TtsPlaylistItem item) {
    final len = item.text.trim().length;
    var ms = 1200 + len * 160;
    if (ms < 1500) ms = 1500;
    if (ms > 18000) ms = 18000;
    return Duration(milliseconds: ms);
  }

  void _armFallbackTimer({required int token, required _TtsPlaylistItem item}) {
    _fallbackTimer?.cancel();
    _fallbackTimer = Timer(_estimateAudioTimeout(item), () {
      if (_tokenSession != _playSession) return;
      if (token != _speakToken) return;
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
        await _advanceAfterItemEnd();
      } finally {
        _handlingAdvance = false;
      }
    });
  }

  int _firstCursorForParagraph(int paragraphIndex) {
    final pl = _playlist;
    if (pl == null) return 0;
    for (var i = 0; i < pl.items.length; i++) {
      if (pl.items[i].index == paragraphIndex) return i;
    }
    return paragraphIndex.clamp(0, (pl.items.length - 1).clamp(0, 999999));
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

    final pl = _playlist;
    if (pl == null || !pl.playable) return;

    _playParagraphs = paragraphs;
    _playViewFp = viewFp;
    vn.value = vn.value.copyWith(viewFp: viewFp);

    final cursor = _firstCursorForParagraph(index);
    if (cursor < 0 || cursor >= pl.items.length) return;
    _playlistCursor = cursor;

    vn.value = vn.value.copyWith(
      playing: true,
      viewFp: viewFp,
      activeChunkIndex: 0,
      activeParagraphIndex:
          deferUiUntilSpeak ? vn.value.activeParagraphIndex : index,
    );

    _pendingActiveParagraphIndex = deferUiUntilSpeak ? index : null;

    if (!deferUiUntilSpeak) {
      scrollTo(index);
    }

    await _playCurrentItem(
        stopBeforePlay: stopBeforeFirstChunk, scrollTo: scrollTo);
  }

  Future<void> _playCurrentItem({
    required bool stopBeforePlay,
    required ScrollToParagraphFn scrollTo,
  }) async {
    if (!ready || !enabled) return;

    final pl = _playlist;
    if (pl == null || !pl.playable) return;
    if (_playlistCursor < 0 || _playlistCursor >= pl.items.length) return;

    final item = pl.items[_playlistCursor];

    _speakToken++;
    final token = _speakToken;
    _handledToken = -1;
    _tokenSession = _playSession;

    _log('PLAY_ITEM', {
      'cursor': _playlistCursor,
      'pIndex': item.index,
      'path': item.path,
      'role': item.role,
      'voice': item.voice,
      'pl_viewFp': pl.viewFp,
      'ui_viewFp': _playViewFp,
      'textHead': item.text.trim().isEmpty
          ? ''
          : item.text.trim().substring(0, item.text.trim().length.clamp(0, 20)),
    });

    int retryCount = 0;
    int waitPollCount = 0;

    // If backend marks this item as not-ready, we prefer to wait/poll.
    while (retryCount < 5) {
      try {
        if (stopBeforePlay && retryCount == 0) {
          _fallbackTimer?.cancel();
          _fallbackTimer = null;
          await _player.stop();
        }

        final pending = _pendingActiveParagraphIndex;
        if (pending != null) {
          vn.value = vn.value.copyWith(activeParagraphIndex: pending);
          scrollTo(pending);
          _pendingActiveParagraphIndex = null;
        } else {
          if (vn.value.activeParagraphIndex != item.index) {
            vn.value = vn.value.copyWith(activeParagraphIndex: item.index);
            scrollTo(item.index);
          }
        }

        vn.value = vn.value.copyWith(
          activeChunkIndex: 0,
          activeRole: item.role,
          activeVoice: item.voice,
        );

        _armFallbackTimer(token: token, item: item);

        final uri = Uri.tryParse(item.path);
        if (uri == null) {
          _triggerAdvance('bad_uri');
          return;
        }

        // ✅ 如果後端告訴我們檔案尚未 ready，就先等它生成好
        if (!item.ready) {
          waitPollCount++;
          if (waitPollCount <= 40) {
            _log('AUDIO_WAIT_NOT_READY', {
              'cursor': _playlistCursor,
              'pIndex': item.index,
              'waitPoll': waitPollCount,
            });
            await _refreshPlaylistIfPossible();
            await Future<void>.delayed(const Duration(milliseconds: 900));
            if (_tokenSession != _playSession || token != _speakToken) return;
            // refresh playlist reference
            final pl2 = _playlist;
            if (pl2 == null || !pl2.playable) return;
            if (_playlistCursor < 0 || _playlistCursor >= pl2.items.length)
              return;
            final newItem = pl2.items[_playlistCursor];
            if (!newItem.ready) {
              // continue waiting without counting as retry
              continue;
            }
          }
        }

        // 先載入音檔
        if (uri.scheme == 'file') {
          await _player.setFilePath(uri.toFilePath());
        } else {
          await _player.setUrl(uri.toString());
        }

        // ✅ 只有真的載入成功且開始播才算 didSpeak
        vn.value = vn.value.copyWith(didSpeak: true, didSpeakFp: _playViewFp);

        // 用 duration(若有) 取代 fallback；duration 沒有就用估算
        final d = _player.duration;
        final timeout = (d == null)
            ? _estimateAudioTimeout(item)
            : Duration(
                milliseconds: (d.inMilliseconds + 800).clamp(2000, 30000));

        _fallbackTimer?.cancel();
        _fallbackTimer = Timer(timeout, () {
          if (_tokenSession != _playSession) return;
          if (token != _speakToken) return;
          _triggerAdvance('fallback_duration');
        });

        await _player.play();
        break; // Success!
      } catch (e) {
        retryCount++;
        _log('AUDIO_RETRY', {'err': e.toString(), 'retry': retryCount});

        if (retryCount >= 5) {
          // 如果真的播不到，不要再直接 abort，我們試著去等 tts_status ready
          final fetchStatus = _fetchTtsStatus;
          if (fetchStatus != null &&
              pl.totalCount > 0 &&
              pl.viewFp.isNotEmpty) {
            _log('AUDIO_POLLING_STATUS', {'err': 'fallback to tts polling'});
            final deadline =
                DateTime.now().add(const Duration(seconds: 20)); // 最多等20秒
            bool recovered = false;
            while (DateTime.now().isBefore(deadline)) {
              await Future<void>.delayed(const Duration(milliseconds: 600));
              if (_tokenSession != _playSession || token != _speakToken) return;

              try {
                final status =
                    await fetchStatus(viewFp: pl.viewFp, count: pl.totalCount);
                if (status.readyCount > _playlistCursor) {
                  // ready 了，更新 URL 後重新進入 retry 的外層
                  if (status.paths.length > _playlistCursor) {
                    final url = status.paths[_playlistCursor];
                    // 不去改 class parameter, 只要不丟 error 就會重試進下一圈
                    // 這邊我們手動把 playlistItem 更新
                    pl.items[_playlistCursor] = _TtsPlaylistItem(
                      index: item.index,
                      path: url,
                      role: item.role,
                      voice: item.voice,
                      text: item.text,
                      format: item.format,
                      ready: true,
                    );
                    retryCount = 0; // 重置 retry
                    recovered = true;
                    break;
                  }
                }
              } catch (e2) {
                // ignore polling error
              }
            }

            if (recovered) {
              continue; // 重新跑一次 loop
            }
          }

          _log('AUDIO_ERROR',
              {'err': e.toString(), 'timeout': 'failed and polling timeout'});
          _triggerAdvance('audio_error');
          return;
        }

        // Wait before retrying
        await Future<void>.delayed(const Duration(milliseconds: 1200));

        // If state changed while waiting, abort retry loop
        if (_tokenSession != _playSession || token != _speakToken) return;
      }
    }
  }

  Future<void> _advanceAfterItemEnd() async {
    if (!vn.value.playing) return;

    final pl = _playlist;
    if (pl == null || !pl.playable) {
      await stop(resetToStart: false);
      return;
    }

    final nextCursor = _playlistCursor + 1;
    if (nextCursor < pl.items.length) {
      _playlistCursor = nextCursor;
      vn.value =
          vn.value.copyWith(activeChunkIndex: vn.value.activeChunkIndex + 1);

      final scroll = _scrollTo ?? (_) {};
      await _playCurrentItem(stopBeforePlay: false, scrollTo: scroll);
      return;
    }

    // playlist finished
    final didSpeak = vn.value.didSpeak;

    await stop(resetToStart: false);

    if (didSpeak) {
      onNarrationEnd?.call();
    }
  }
}
