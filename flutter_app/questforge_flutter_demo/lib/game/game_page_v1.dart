// lib/game/game_page_v1.dart
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:questforge_flutter_demo/bridge/bridge_controller_v2.dart';
import 'package:questforge_flutter_demo/bridge/overlay_manager.dart';
import 'package:questforge_ui_contract/questforge_contract.dart';

import 'ui_phase.dart';
import 'widgets/accuse_panel.dart';
import 'widgets/choice_card_v2.dart';
import 'widgets/story_card_v2.dart';

class GamePageV1 extends StatefulWidget {
  const GamePageV1({
    super.key,
    required this.controller,
  });

  final BridgeControllerV2 controller;

  @override
  State<GamePageV1> createState() => _GamePageV1State();
}

class _GamePageV1State extends State<GamePageV1> with WidgetsBindingObserver {
  final OverlayManagerV2 _overlays = const OverlayManagerV2();

  // ---------------------------
  // Day28-A: single phase
  // ---------------------------
  UiPhase _derivePhase({
    required bool overlayShowing,
    required bool chooseLocked,
    required NodeView? view,
    required bool hasEnd,
  }) {
    if (hasEnd) return UiPhase.ended;
    if (overlayShowing) return UiPhase.overlay;
    if (chooseLocked) return UiPhase.sending;

    final hasChoices = (view?.choices.isNotEmpty ?? false);
    return hasChoices ? UiPhase.choosing : UiPhase.reading;
  }

  // ---------------------------
  // Day25-A: narration font only
  // ---------------------------
  double _fontScale = 1.0;
  static const double _minScale = 0.9;
  static const double _maxScale = 1.4;
  static const double _step = 0.1;

  // Day24-E: choice highlight state
  int? _pressedChoiceIndex;
  Timer? _pressedClearTimer;

  // ---------------------------
  // Day29-B: autoplay on view enter
  // ---------------------------
  bool _autoPlayPending = false;
  String _lastAutoPlayedFingerprint = '';

  // ---------------------------
  // Day28-B: sending watchdog
  // ---------------------------
  Timer? _sendingWatchdog;
  static const Duration _watchdogDur = Duration(seconds: 6);

  void _armSendingWatchdog() {
    _sendingWatchdog?.cancel();
    _sendingWatchdog = Timer(_watchdogDur, () {
      if (!mounted) return;

      // 若還卡在 sending，就解鎖（避免永遠轉圈）
      if (widget.controller.chooseLockVN.value) {
        widget.controller.unlockChoose();
      }

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('剛剛有點卡住了，我們再試一次～')),
      );
    });
  }

  void _cancelSendingWatchdog() {
    _sendingWatchdog?.cancel();
    _sendingWatchdog = null;
  }

  // ---------------------------
  // Day28-C: TTS enable (ask once)
  // ---------------------------
  final FlutterTts _tts = FlutterTts();
  bool _ttsReady = false;
  bool _ttsEnabled = true;
  bool _ttsAskShown = false;

  bool _paraPlaying = false;
  bool _speakJobActive = false;

  // paragraph index in narration
  int _activeParagraphIndex = 0;

  // ✅ Day29-C: chunked TTS to mimic "pause/resume"
  // - 先把段落拆成比較自然的片段（約 12~28 字、優先標點斷句）
  // - 暫停後再播放：從「目前 chunk」接續，而不是整段從頭
  static const int _chunkMinChars = 12;
  static const int _chunkMaxChars = 28;

  List<String> _ttsChunks = const <String>[];
  int _activeChunkIndex = 0;

  // Day26-A: lifecycle stability
  bool _appInactive = false;

  // completion handler needs latest paragraphs
  List<StoryParagraph> _latestParagraphs = const <StoryParagraph>[];

  // view change detection
  String _lastViewFingerprint = '';

  // ✅ Hard reset epoch for macOS resume (scroll/gesture stuck workaround)
  int _resumeEpoch = 0;
  Key _pageRebuildKey = const ValueKey('page_0');

  // Day25-C: story card key (scrollToParagraph)
  final GlobalKey<StoryCardV2State> _storyKey = GlobalKey<StoryCardV2State>();

  // ---------------------------
  // Day29-A: auto continue (TTS end -> choose(0))
  // ---------------------------

  bool _isMidReasonNode(NodeView view) {
    final id = view.nodeId.toLowerCase();
    return id.contains('mid_reason');
  }

  bool _isEndingNode(NodeView view) {
    final id = view.nodeId.toLowerCase();
    return id.contains('ending') || id.contains('quit');
  }

  bool _isAutoContinueNode(NodeView view) {
    if (_isMidReasonNode(view)) return false;
    if (_isAccuseNode(view)) return false;
    if (_isEndingNode(view)) return false;

    final cs = view.choices;
    if (cs.length != 1) return false;

    final t = cs.first.text.trim();
    return t.startsWith('繼續') || t == '下一段';
  }

  bool _overlayShowingFromState(BridgeUiStateV2 s) {
    return s.bundle.ask != null || s.bundle.quiz != null || s.bundle.end != null;
  }

  void _tryAutoContinueAfterTtsEnd() {
    if (!mounted) return;
    if (_appInactive) return;

    final s = widget.controller.stateVN.value;
    if (_overlayShowingFromState(s)) return;
    if (widget.controller.chooseLockVN.value) return;

    final v = s.view;
    if (v == null) return;
    if (!_isAutoContinueNode(v)) return;

    final idx = v.choices.first.index;
    widget.controller.sendChoose(idx);
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _initTts();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) async {
    final inactive = state == AppLifecycleState.inactive || state == AppLifecycleState.paused;

    if (inactive) {
      _appInactive = true;
      await _stopParagraphPlayback(resetToStart: false);

      _pressedClearTimer?.cancel();
      _pressedClearTimer = null;
      _cancelSendingWatchdog();

      if (mounted) {
        setState(() {
          _pressedChoiceIndex = null;
        });
      }
      return;
    }

    if (state == AppLifecycleState.resumed) {
      _appInactive = false;

      FocusManager.instance.primaryFocus?.unfocus();
      try {
        await SystemChannels.textInput.invokeMethod('TextInput.hide');
      } catch (_) {}

      await _stopParagraphPlayback(resetToStart: false);

      if (!mounted) return;
      setState(() {
        _resumeEpoch++;
        _pageRebuildKey = ValueKey('page_$_resumeEpoch');
      });
    }
  }

  Future<void> _initTts() async {
    try {
      await _tts.setLanguage('zh-TW');
    } catch (_) {}

    try {
      await _tts.setSpeechRate(0.45);
      await _tts.setPitch(1.0);
    } catch (_) {}

    _tts.setCompletionHandler(() {
      if (!mounted) return;
      // ignore: discarded_futures
      _continueAfterCompletion(_latestParagraphs);
    });

    _tts.setCancelHandler(() {});
    _tts.setErrorHandler((msg) {
      if (!mounted) return;
      setState(() {
        _paraPlaying = false;
        _speakJobActive = false;
      });
    });

    if (!mounted) return;
    setState(() => _ttsReady = true);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);

    _pressedClearTimer?.cancel();
    _pressedClearTimer = null;

    _cancelSendingWatchdog();

    // ignore: discarded_futures
    _stopParagraphPlayback(resetToStart: false);
    _tts.stop();

    super.dispose();
  }

  // ------------------------------------------------------------
  // Quit
  // ------------------------------------------------------------
  Future<void> _confirmQuit(BuildContext context) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          title: const Text('離開遊戲？'),
          content: const Text('現在離開會結束本次遊玩流程。'),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: const Text('離開'),
            ),
          ],
        );
      },
    );

    if (ok == true) {
      widget.controller.sendEndActionSpec(
        UiActionSpecV2(
          kind: UiActionKindV2.endFlow,
          id: 'quit',
          text: '離開',
          data: null,
        ),
      );
    }
  }

  // ------------------------------------------------------------
  // Day27-D: accuse node detector + confirm flow
  // ------------------------------------------------------------
  bool _isAccuseNode(NodeView view) {
    final id = view.nodeId.toLowerCase();
    final title = view.title;
    return id.contains('accuse') || title.contains('指認') || title.contains('推理') || title.contains('最後');
  }

  Future<bool> _confirmAccuseChoice(BuildContext context, {required String name}) async {
    final ok = await showModalBottomSheet<bool>(
      context: context,
      useSafeArea: true,
      isScrollControlled: false,
      builder: (ctx) {
        return AccuseConfirmSheet(
          name: name,
          onCancel: () => Navigator.of(ctx).pop(false),
          onConfirm: () => Navigator.of(ctx).pop(true),
        );
      },
    );
    return ok == true;
  }

  // ------------------------------------------------------------
  // Day25-A: narration font only
  // ------------------------------------------------------------
  void _fontDown() {
    setState(() => _fontScale = (_fontScale - _step).clamp(_minScale, _maxScale));
  }

  void _fontUp() {
    setState(() => _fontScale = (_fontScale + _step).clamp(_minScale, _maxScale));
  }

  // ------------------------------------------------------------
  // Day24-E: choice highlight + hook
  // ------------------------------------------------------------
  void _setPressedChoice(int index, {Duration autoClear = const Duration(milliseconds: 900)}) {
    _pressedClearTimer?.cancel();
    _pressedClearTimer = null;

    setState(() => _pressedChoiceIndex = index);

    _pressedClearTimer = Timer(autoClear, () {
      if (!mounted) return;
      setState(() => _pressedChoiceIndex = null);
    });
  }

  void _clearPressedChoice() {
    _pressedClearTimer?.cancel();
    _pressedClearTimer = null;
    if (_pressedChoiceIndex != null) {
      setState(() => _pressedChoiceIndex = null);
    }
  }

  void _onChoiceTapHook(ChoiceView choice) {
    // future hook
    // HapticFeedback.selectionClick();
    // playSfx('tap');
  }

  // ------------------------------------------------------------
  // Day28-C: ask once dialog
  // ------------------------------------------------------------
  Future<void> _maybeAskTtsOnce() async {
    if (_ttsAskShown) return;
    _ttsAskShown = true;

    if (!mounted) return;
    final enabled = await showModalBottomSheet<bool>(
      context: context,
      useSafeArea: true,
      builder: (ctx) {
        return Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 44,
                height: 5,
                decoration: BoxDecoration(
                  color: Theme.of(ctx).colorScheme.outlineVariant,
                  borderRadius: BorderRadius.circular(999),
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Text(
                    '要開啟語音朗讀嗎？',
                    style: Theme.of(ctx).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w900),
                  ),
                  const Spacer(),
                  IconButton(onPressed: () => Navigator.of(ctx).pop(false), icon: const Icon(Icons.close)),
                ],
              ),
              const SizedBox(height: 8),
              const Align(
                alignment: Alignment.centerLeft,
                child: Text('可以隨時用播放按鈕朗讀故事。'),
              ),
              const SizedBox(height: 14),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () => Navigator.of(ctx).pop(false),
                      child: const Text('先不用'),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: FilledButton(
                      onPressed: () => Navigator.of(ctx).pop(true),
                      child: const Text('開啟語音'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        );
      },
    );

    if (!mounted) return;
    final on = enabled ?? false;

    setState(() {
      _ttsEnabled = on;
    });

    // ✅ 開啟語音後：立刻自動播放當前節點
    if (on) {
      final v = widget.controller.stateVN.value.view;
      if (v != null) {
        _autoPlayPending = true;
        _maybeAutoPlayOnEnter(
          view: v,
          overlayShowing: _overlayShowingFromState(widget.controller.stateVN.value),
          chooseLocked: widget.controller.chooseLockVN.value,
        );
      }
    }
  }

  void _hintEnableTts() {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('語音目前關閉～想聽故事可以先開啟語音')),
    );
  }

  // ------------------------------------------------------------
  // Day29-C: "more like real pause" chunk builder
  // ------------------------------------------------------------

  bool _isStrongPunc(String s) => s.contains(RegExp(r'[。！？!?]'));
  bool _isMidPunc(String s) => s.contains(RegExp(r'[，,、；;：:]'));
  bool _isAnyPunc(String s) => _isStrongPunc(s) || _isMidPunc(s) || s.contains('…');

  Duration _gapAfterChunk(String chunk) {
    // 讓銜接更像自然朗讀：標點稍微停一下（不會太明顯）
    if (_isStrongPunc(chunk)) return const Duration(milliseconds: 220);
    if (_isMidPunc(chunk) || chunk.contains('…')) return const Duration(milliseconds: 140);
    return const Duration(milliseconds: 70);
  }

  List<String> _splitByPunctuationKeeping(String text) {
    final t = text.trim();
    if (t.isEmpty) return const <String>[];

    // 用 regex 切出「句子片段（含結尾標點）」
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

    // 先用逗號/頓號拆
    final parts = t
        .split(RegExp(r'(?<=[，,、；;：:])'))
        .map((e) => e.trim())
        .where((e) => e.isNotEmpty)
        .toList();

    // 如果拆完還是很長（例如沒有逗號），就固定切片
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

    // 先把太長單位再拆小
    final expanded = <String>[];
    for (final u in units) {
      if (u.length > _chunkMaxChars) {
        expanded.addAll(_splitLongByCommaOrFixed(u));
      } else {
        expanded.add(u);
      }
    }

    // 再做「合併」：盡量落在 12~28 字
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
        // 如果單片就已經接近上限且有標點，就先出
        if (buf.length >= _chunkMinChars && _isAnyPunc(buf)) flush();
        continue;
      }

      final candidate = '$buf$p';
      if (candidate.length <= _chunkMaxChars) {
        buf = candidate;

        // 有標點且已達最小字數：出一段（聽起來更像一句一句）
        if (buf.length >= _chunkMinChars && _isAnyPunc(buf)) {
          flush();
        }
        continue;
      }

      // candidate 超過 max：先把 buf 送出，再以 p 當新 buf
      flush();
      buf = p;

      if (buf.length >= _chunkMinChars && _isAnyPunc(buf)) flush();
    }

    flush();

    // 最後：避免超短尾巴（<=4）造成很碎，併回前一段
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

  // ------------------------------------------------------------
  // Day25-C: paragraph playback with real TTS (chunked)
  // ------------------------------------------------------------
  Future<void> _stopParagraphPlayback({required bool resetToStart}) async {
    _speakJobActive = false;
    try {
      await _tts.stop();
    } catch (_) {}

    if (!mounted) return;
    setState(() {
      _paraPlaying = false;

      if (resetToStart) {
        _activeParagraphIndex = 0;
        _ttsChunks = const <String>[];
        _activeChunkIndex = 0;
      }
    });
  }

  Future<void> _speakCurrentChunk() async {
    if (!_ttsReady) return;
    if (!_ttsEnabled) {
      _hintEnableTts();
      return;
    }
    if (_appInactive) return;
    if (_ttsChunks.isEmpty) return;
    if (_activeChunkIndex < 0 || _activeChunkIndex >= _ttsChunks.length) return;

    if (_speakJobActive) return;
    _speakJobActive = true;

    final text = _ttsChunks[_activeChunkIndex].trim();
    if (text.isEmpty) {
      _speakJobActive = false;
      return;
    }

    try {
      await _tts.stop();
      await _tts.speak(text);
    } catch (_) {
      if (!mounted) return;
      setState(() => _paraPlaying = false);
    } finally {
      _speakJobActive = false;
    }
  }

  Future<void> _speakParagraph(int index, List<StoryParagraph> paragraphs) async {
    if (!_ttsReady) return;
    if (!_ttsEnabled) {
      _hintEnableTts();
      return;
    }
    if (_appInactive) return;
    if (paragraphs.isEmpty) return;
    if (index < 0 || index >= paragraphs.length) return;

    final raw = paragraphs[index].text.trim();
    if (raw.isEmpty) return;

    final chunks = _buildChunksForParagraph(raw);
    if (chunks.isEmpty) return;

    if (!mounted) return;
    setState(() {
      _activeParagraphIndex = index;
      _ttsChunks = chunks;
      _activeChunkIndex = 0;
      _paraPlaying = true;
    });

    _storyKey.currentState?.scrollToParagraph(index);
    await _speakCurrentChunk();
  }

  Future<void> _continueAfterCompletion(List<StoryParagraph> paragraphs) async {
    if (!mounted) return;
    if (!_paraPlaying) return;
    if (_appInactive) return;

    // ✅ chunk 間做小停頓，讓銜接更像自然朗讀（不會像機器連珠）
    if (_ttsChunks.isNotEmpty && _activeChunkIndex >= 0 && _activeChunkIndex < _ttsChunks.length) {
      final gap = _gapAfterChunk(_ttsChunks[_activeChunkIndex]);
      if (gap.inMilliseconds > 0) {
        await Future<void>.delayed(gap);
      }
    }

    // 1) 先推進 chunk（同段落）
    final nextChunk = _activeChunkIndex + 1;
    if (_ttsChunks.isNotEmpty && nextChunk < _ttsChunks.length) {
      setState(() => _activeChunkIndex = nextChunk);
      await _speakCurrentChunk();
      return;
    }

    // 2) chunk 播完了 → 推進下一段落
    if (paragraphs.isEmpty) {
      await _stopParagraphPlayback(resetToStart: false);
      return;
    }

    final nextPara = _activeParagraphIndex + 1;

    // ✅ 本節點播完：停止播放，並嘗試 auto-continue
    if (nextPara >= paragraphs.length) {
      await _stopParagraphPlayback(resetToStart: false);
      _tryAutoContinueAfterTtsEnd();
      return;
    }

    await _speakParagraph(nextPara, paragraphs);
  }

  Future<void> _toggleParagraphPlay(List<StoryParagraph> paragraphs) async {
    if (paragraphs.isEmpty) return;
    if (_appInactive) return;

    if (!_ttsEnabled) {
      _hintEnableTts();
      return;
    }

    if (_paraPlaying) {
      // ✅ pause：只 stop，不動 index（保持續播點）
      await _stopParagraphPlayback(resetToStart: false);
      return;
    }

    // ✅ resume：如果已經有 chunks，就從目前 chunk 接續
    if (_ttsChunks.isNotEmpty && _activeChunkIndex < _ttsChunks.length) {
      setState(() => _paraPlaying = true);
      await _speakCurrentChunk();
      return;
    }

    // 否則：重建當前段落的 chunks 從頭播
    final i = _activeParagraphIndex.clamp(0, paragraphs.length - 1);
    await _speakParagraph(i, paragraphs);
  }

  Future<void> _prevParagraph(List<StoryParagraph> paragraphs) async {
    if (paragraphs.isEmpty) return;
    final nextIndex = (_activeParagraphIndex - 1).clamp(0, paragraphs.length - 1);
    final wasPlaying = _paraPlaying;

    await _stopParagraphPlayback(resetToStart: false);
    if (!mounted) return;

    setState(() {
      _activeParagraphIndex = nextIndex;
      _ttsChunks = const <String>[];
      _activeChunkIndex = 0;
    });
    _storyKey.currentState?.scrollToParagraph(nextIndex);

    if (wasPlaying) await _speakParagraph(nextIndex, paragraphs);
  }

  Future<void> _nextParagraph(List<StoryParagraph> paragraphs) async {
    if (paragraphs.isEmpty) return;
    final nextIndex = (_activeParagraphIndex + 1).clamp(0, paragraphs.length - 1);
    final wasPlaying = _paraPlaying;

    await _stopParagraphPlayback(resetToStart: false);
    if (!mounted) return;

    setState(() {
      _activeParagraphIndex = nextIndex;
      _ttsChunks = const <String>[];
      _activeChunkIndex = 0;
    });
    _storyKey.currentState?.scrollToParagraph(nextIndex);

    if (wasPlaying) await _speakParagraph(nextIndex, paragraphs);
  }

  Future<void> _jumpToParagraph(int index, List<StoryParagraph> paragraphs) async {
    if (paragraphs.isEmpty) return;
    final nextIndex = index.clamp(0, paragraphs.length - 1);
    final wasPlaying = _paraPlaying;

    await _stopParagraphPlayback(resetToStart: false);
    if (!mounted) return;

    setState(() {
      _activeParagraphIndex = nextIndex;
      _ttsChunks = const <String>[];
      _activeChunkIndex = 0;
    });
    _storyKey.currentState?.scrollToParagraph(nextIndex);

    if (wasPlaying) await _speakParagraph(nextIndex, paragraphs);
  }

  // ------------------------------------------------------------
  // unlock local highlight/watchdog when view changes
  // ------------------------------------------------------------
  String _fingerprint(NodeView v) => '${v.nodeId}|${v.title}|${v.narration.length}|${v.choices.length}';

  Future<void> _onViewMaybeChanged(NodeView? view) async {
    if (view == null) return;
    final fp = _fingerprint(view);
    if (fp == _lastViewFingerprint) return;

    _lastViewFingerprint = fp;

    _cancelSendingWatchdog();

    if (_pressedChoiceIndex != null) Future.microtask(_clearPressedChoice);

    // 節點切換：停止播放並回到第 0 段
    await _stopParagraphPlayback(resetToStart: true);

    // ✅ 只要 TTS 已啟用，進新節點就準備自動播放
    if (_ttsEnabled) {
      _autoPlayPending = true;
    }

    if (!mounted) return;
    setState(() {});
  }

  void _maybeAutoPlayOnEnter({
    required NodeView view,
    required bool overlayShowing,
    required bool chooseLocked,
  }) {
    if (!_autoPlayPending) return;
    if (!mounted) return;

    if (!_ttsReady) return;
    if (!_ttsEnabled) return;

    if (_appInactive) return;
    if (overlayShowing) return;
    if (chooseLocked) return;

    final fp = _fingerprint(view);
    if (_lastAutoPlayedFingerprint == fp) {
      _autoPlayPending = false;
      return;
    }

    final paragraphs = parseParagraphs(view.narration);
    if (paragraphs.isEmpty) {
      _autoPlayPending = false;
      return;
    }

    _lastAutoPlayedFingerprint = fp;
    _autoPlayPending = false;

    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      if (_appInactive) return;
      if (!_ttsEnabled) return;

      await _stopParagraphPlayback(resetToStart: true);
      await _speakParagraph(0, paragraphs);
    });
  }

  // ------------------------------------------------------------
  // Build
  // ------------------------------------------------------------
  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<BridgeUiStateV2>(
      valueListenable: widget.controller.stateVN,
      builder: (context, state, _) {
        final view = state.view;

        final ask = state.bundle.ask;
        final quiz = state.bundle.quiz;
        final end = state.bundle.end;

        final overlayShowing = (ask != null) || (quiz != null) || (end != null);
        final chooseLocked = widget.controller.chooseLockVN.value;

        final phase = _derivePhase(
          overlayShowing: overlayShowing,
          chooseLocked: chooseLocked,
          view: view,
          hasEnd: end != null,
        );

        // 進第一個 view 時問一次 TTS
        if (view != null && !_ttsAskShown) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            // ignore: discarded_futures
            _maybeAskTtsOnce();
          });
        }

        if (view != null) {
          // ignore: discarded_futures
          _onViewMaybeChanged(view);
        }

        // overlay / sending / ended 都一定停播放
        if ((phase.blockAllTap) && _paraPlaying) {
          // ignore: discarded_futures
          _stopParagraphPlayback(resetToStart: false);
        }

        // sending watchdog
        if (phase == UiPhase.sending) {
          _armSendingWatchdog();
        } else {
          _cancelSendingWatchdog();
        }

        final overlay = _overlays.buildOverlay(
          context: context,
          ask: ask,
          quiz: quiz,
          end: end,
          onSubmitReasons: (ids, text) {
            widget.controller.sender.sendSetReasons(reasonIds: ids, text: text);
          },
          onCloseAsk: () {},
          onSubmitQuiz: (answers) {
            widget.controller.sender.sendConfirmQuizAnswerList(answers);
          },
          onCloseQuiz: () {
            widget.controller.sender.sendConfirmQuizAnswerList(
              const <Object?>[],
              skipped: true,
            );
          },
          endLockVN: widget.controller.endActionLockVN,
          pendingEndVN: widget.controller.pendingEndActionIdVN,
          onTapEndAction: (action) => widget.controller.sendEndActionSpec(action),
          onCloseEnd: widget.controller.unlockEndAction,
        );

        final mq = MediaQuery.of(context);
        final narrationScaled = mq.copyWith(textScaler: TextScaler.linear(_fontScale));

        // 每次 build 更新最新段落（給 completion handler 用）
        if (view != null) {
          _latestParagraphs = parseParagraphs(view.narration);
          _maybeAutoPlayOnEnter(
            view: view,
            overlayShowing: overlayShowing,
            chooseLocked: chooseLocked,
          );
        } else {
          _latestParagraphs = const <StoryParagraph>[];
        }

        return Stack(
          children: [
            if (view == null)
              const Center(child: Text('尚未開始（請由 Dev Shell Start+Hello）'))
            else
              Builder(
                builder: (context) {
                  final paragraphs = _latestParagraphs;
                  final active = paragraphs.isEmpty ? 0 : _activeParagraphIndex.clamp(0, paragraphs.length - 1);

                  final isAccuse = _isAccuseNode(view);

                  return ListView(
                    key: _pageRebuildKey,
                    padding: const EdgeInsets.all(16),
                    children: [
                      _PageHeader(
                        title: view.title,
                        fontScale: _fontScale,
                        onDown: phase.allowTopActions ? _fontDown : null,
                        onUp: phase.allowTopActions ? _fontUp : null,
                      ),
                      const SizedBox(height: 10),
                      MediaQuery(
                        data: narrationScaled,
                        child: StoryCardV2(
                          key: _storyKey,
                          rebuildEpoch: _resumeEpoch,
                          chapterLabel: '第 ${_safeChapterNumber(view.nodeId)} 段',
                          paragraphs: paragraphs,
                          activeIndex: active,
                          isPlaying: _paraPlaying,
                          ttsReady: _ttsReady,
                          scrollEnabled: phase.allowStoryScroll,
                          onTogglePlay: phase.allowTopActions ? () => _toggleParagraphPlay(paragraphs) : null,
                          onPrev: phase.allowTopActions ? () => _prevParagraph(paragraphs) : null,
                          onNext: phase.allowTopActions ? () => _nextParagraph(paragraphs) : null,
                          onTapParagraph: phase.allowTopActions ? (i) => _jumpToParagraph(i, paragraphs) : null,
                        ),
                      ),

                      if (isAccuse) ...[
                        const SizedBox(height: 10),
                        const AccusePanel(
                          title: '最後推理',
                          hint: '你想選誰？不用打字，直接點一下。',
                        ),
                      ],

                      const SizedBox(height: 14),

                      ...view.choices.map((c) {
                        final disabled = !phase.allowChoiceTap || !c.enabled;
                        final highlighted = _pressedChoiceIndex == c.index;
                        final pendingThis = chooseLocked && _pressedChoiceIndex == c.index;

                        return Padding(
                          padding: const EdgeInsets.only(bottom: 12),
                          child: ChoiceCardV2(
                            index: c.index,
                            text: c.text,
                            enabled: !disabled,
                            highlighted: highlighted,
                            pending: pendingThis,
                            onTap: () async {
                              if (disabled) return;

                              if (_paraPlaying) await _stopParagraphPlayback(resetToStart: false);

                              _setPressedChoice(c.index);
                              _onChoiceTapHook(c);

                              if (isAccuse) {
                                final ok = await _confirmAccuseChoice(context, name: c.text);
                                if (!ok) return;
                              }

                              if (!mounted) return;

                              final ok = widget.controller.sendChoose(c.index);
                              if (!ok) return;
                            },
                          ),
                        );
                      }),

                      if (phase == UiPhase.sending && !overlayShowing) ...[
                        const SizedBox(height: 4),
                        Text(
                          '送出中…請稍等一下',
                          style: Theme.of(context).textTheme.labelMedium?.copyWith(
                                color: Theme.of(context).colorScheme.outline,
                              ),
                        ),
                        const SizedBox(height: 10),
                      ],
                      const SizedBox(height: 16),
                      const Divider(),
                      const SizedBox(height: 8),
                      OutlinedButton.icon(
                        onPressed: phase.blockAllTap
                            ? null
                            : () async {
                                if (_paraPlaying) await _stopParagraphPlayback(resetToStart: false);
                                await _confirmQuit(context);
                              },
                        icon: const Icon(Icons.exit_to_app),
                        label: const Text('離開'),
                      ),
                    ],
                  );
                },
              ),
            if (overlay != null) overlay,
          ],
        );
      },
    );
  }

  static int _safeChapterNumber(String nodeId) {
    final m = RegExp(r'(\d+)').firstMatch(nodeId);
    return int.tryParse(m?.group(1) ?? '') ?? 1;
  }
}

// ------------------------------------------------------------
// UI: Header
// ------------------------------------------------------------
class _PageHeader extends StatelessWidget {
  const _PageHeader({
    required this.title,
    required this.fontScale,
    required this.onDown,
    required this.onUp,
  });

  final String title;
  final double fontScale;
  final VoidCallback? onDown;
  final VoidCallback? onUp;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Text(
            title,
            style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
          ),
        ),
        const SizedBox(width: 8),
        _FontControls(
          scale: fontScale,
          onDown: onDown,
          onUp: onUp,
        ),
      ],
    );
  }
}

class _FontControls extends StatelessWidget {
  const _FontControls({
    required this.scale,
    required this.onDown,
    required this.onUp,
  });

  final double scale;
  final VoidCallback? onDown;
  final VoidCallback? onUp;

  @override
  Widget build(BuildContext context) {
    final percent = (scale * 100).round();

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        IconButton(
          tooltip: '故事字體縮小',
          onPressed: onDown,
          icon: const Icon(Icons.text_decrease),
        ),
        Text('$percent%', style: Theme.of(context).textTheme.labelSmall),
        IconButton(
          tooltip: '故事字體放大',
          onPressed: onUp,
          icon: const Icon(Icons.text_increase),
        ),
      ],
    );
  }
}
