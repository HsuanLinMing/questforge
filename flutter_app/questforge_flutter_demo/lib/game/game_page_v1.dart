// lib/game/game_page_v1.dart
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:questforge_flutter_demo/bridge/bridge_controller_v2.dart';
import 'package:questforge_flutter_demo/bridge/overlay_manager.dart';
import 'package:questforge_ui_contract/questforge_contract.dart';

import 'tts/tts_playback_controller.dart';
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
  // UI phase
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
  // narration font
  // ---------------------------
  double _fontScale = 1.0;
  static const double _minScale = 0.9;
  static const double _maxScale = 1.4;
  static const double _step = 0.1;

  void _fontDown() => setState(() => _fontScale = (_fontScale - _step).clamp(_minScale, _maxScale));
  void _fontUp() => setState(() => _fontScale = (_fontScale + _step).clamp(_minScale, _maxScale));

  // ---------------------------
  // choice highlight
  // ---------------------------
  int? _pressedChoiceIndex;
  Timer? _pressedClearTimer;

  void _setPressedChoice(int index, {Duration autoClear = const Duration(milliseconds: 900)}) {
    _pressedClearTimer?.cancel();
    _pressedClearTimer = Timer(autoClear, () {
      if (!mounted) return;
      setState(() => _pressedChoiceIndex = null);
    });
    setState(() => _pressedChoiceIndex = index);
  }

  void _clearPressedChoice() {
    _pressedClearTimer?.cancel();
    _pressedClearTimer = null;
    if (_pressedChoiceIndex != null) setState(() => _pressedChoiceIndex = null);
  }

  void _onChoiceTapHook(ChoiceView choice) {
    // future hook
    // HapticFeedback.selectionClick();
  }

  // ---------------------------
  // sending watchdog
  // ---------------------------
  Timer? _sendingWatchdog;
  static const Duration _watchdogDur = Duration(seconds: 6);

  void _armSendingWatchdog() {
    _sendingWatchdog?.cancel();
    _sendingWatchdog = Timer(_watchdogDur, () {
      if (!mounted) return;

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
  // NAV debounce
  // ---------------------------
  bool _navBusy = false;
  Timer? _navBusyTimer;

  bool _tryLockNav([Duration dur = const Duration(milliseconds: 260)]) {
    if (_navBusy) return false;
    _navBusy = true;
    _navBusyTimer?.cancel();
    _navBusyTimer = Timer(dur, () => _navBusy = false);
    return true;
  }

  // ---------------------------
  // TTS controller (瘦身關鍵)
  // ---------------------------
  late final TtsPlaybackController _ttsCtl = TtsPlaybackController(
    logger: (tag, extra) {
      // ignore: avoid_print
      print('[GamePageV1][$tag] $extra');
    },
  );

  bool _ttsAskShown = false;
  bool _appInactive = false;

  // story card key
  final GlobalKey<StoryCardV2State> _storyKey = GlobalKey<StoryCardV2State>();

  // view change detection
  String _lastViewFingerprint = '';
  bool _handlingViewChange = false;
  String _lastAutoPlayedFingerprint = '';

  // macOS resume workaround
  int _resumeEpoch = 0;
  Key _pageRebuildKey = const ValueKey('page_0');

  // ---------------------------
  // auto-continue node
  // ---------------------------
  bool _isAccuseNode(NodeView view) {
    final id = view.nodeId.toLowerCase();
    final title = view.title;
    return id.contains('accuse') || title.contains('指認') || title.contains('推理') || title.contains('最後');
  }

  bool _isMidReasonNode(NodeView view) => view.nodeId.toLowerCase().contains('mid_reason');

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

  // ---------------------------
  // lifecycle
  // ---------------------------
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // ignore: discarded_futures
    _ttsCtl.init();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);

    _pressedClearTimer?.cancel();
    _pressedClearTimer = null;

    _cancelSendingWatchdog();

    _navBusyTimer?.cancel();
    _navBusyTimer = null;

    // ignore: discarded_futures
    _ttsCtl.dispose();

    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) async {
    final inactive = state == AppLifecycleState.inactive || state == AppLifecycleState.paused;

    if (inactive) {
      _appInactive = true;
      await _ttsCtl.stop(resetToStart: false);

      _pressedClearTimer?.cancel();
      _pressedClearTimer = null;
      _cancelSendingWatchdog();

      if (mounted) setState(() => _pressedChoiceIndex = null);
      return;
    }

    if (state == AppLifecycleState.resumed) {
      _appInactive = false;

      FocusManager.instance.primaryFocus?.unfocus();
      try {
        await SystemChannels.textInput.invokeMethod('TextInput.hide');
      } catch (_) {}

      await _ttsCtl.stop(resetToStart: false);

      if (!mounted) return;
      setState(() {
        _resumeEpoch++;
        _pageRebuildKey = ValueKey('page_$_resumeEpoch');
      });
    }
  }

  // ---------------------------
  // ask once dialog
  // ---------------------------
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
    _ttsCtl.setEnabled(on);
  }

  // ---------------------------
  // view changed / autoplay
  // ---------------------------
  String _fingerprint(NodeView v) => '${v.nodeId}|${v.title}|${v.narration.length}|${v.choices.length}';

  void _scheduleHandleViewChanged(NodeView view, List<StoryParagraph> paragraphs) {
    final fp = _fingerprint(view);
    if (fp == _lastViewFingerprint) return;
    _lastViewFingerprint = fp;

    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      if (_handlingViewChange) return;

      _handlingViewChange = true;
      try {
        _cancelSendingWatchdog();
        if (_pressedChoiceIndex != null) _clearPressedChoice();

        // autoplay 只播一次
        final allowAutoPlay = _ttsCtl.enabled && _ttsCtl.ready && !_appInactive;
        final fp2 = _fingerprint(view);
        final doAutoPlay = allowAutoPlay && (_lastAutoPlayedFingerprint != fp2);
        if (doAutoPlay) _lastAutoPlayedFingerprint = fp2;

        await _ttsCtl.handleViewChanged(
          view: view,
          paragraphs: paragraphs,
          viewFp: fp2,
          autoPlay: doAutoPlay,
          scrollTo: (i) => _storyKey.currentState?.scrollToParagraph(i),
        );
      } finally {
        _handlingViewChange = false;
      }
    });
  }

  // ---------------------------
  // quit
  // ---------------------------
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

  // ---------------------------
  // build
  // ---------------------------
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

        if (view != null && !_ttsAskShown) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            // ignore: discarded_futures
            _maybeAskTtsOnce();
          });
        }

        if (view == null) {
          return const Center(child: Text('尚未開始（請由 Dev Shell Start+Hello）'));
        }

        final viewFp = _fingerprint(view);
        final paragraphs = parseParagraphs(view.narration);

        _scheduleHandleViewChanged(view, paragraphs);

        // overlay / sending / ended -> stop playback
        if ((phase.blockAllTap) && _ttsCtl.playing) {
          // ignore: discarded_futures
          _ttsCtl.stop(resetToStart: false);
        }

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

        final isAccuse = _isAccuseNode(view);

        return ValueListenableBuilder<TtsPlaybackState>(
          valueListenable: _ttsCtl.vn,
          builder: (context, ttsState, __) {
            // ✅ 這裡才用 ttsState 重新算 active，UI 才會跟著跳
            final activeNow = paragraphs.isEmpty
                ? 0
                : ttsState.activeParagraphIndex.clamp(0, paragraphs.length - 1);

            // ignore: avoid_print
            print('[UI] active=${ttsState.activeParagraphIndex} playing=${ttsState.playing}');

            // ✅ 只有在「真的播放結束（stop）且播放到最後段」才嘗試 auto continue
            if (!ttsState.playing && paragraphs.isNotEmpty) {
              final atEnd = ttsState.activeParagraphIndex >= paragraphs.length - 1;
              if (atEnd) {
                Future.microtask(() => _tryAutoContinueAfterTtsEnd());
              }
            }

            return Stack(
              children: [
                ListView(
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
                        activeIndex: activeNow, // ✅ 用 activeNow
                        isPlaying: ttsState.playing,
                        ttsReady: ttsState.ready,
                        scrollEnabled: phase.allowStoryScroll,
                        onTogglePlay: phase.allowTopActions
                            ? () => _ttsCtl.togglePlay(
                                  paragraphs: paragraphs,
                                  viewFp: viewFp,
                                  scrollTo: (i) => _storyKey.currentState?.scrollToParagraph(i),
                                )
                            : null,
                        onPrev: phase.allowTopActions
                            ? () async {
                                if (!_tryLockNav()) return;
                                await _ttsCtl.prev(
                                  paragraphs: paragraphs,
                                  viewFp: viewFp,
                                  scrollTo: (i) => _storyKey.currentState?.scrollToParagraph(i),
                                );
                              }
                            : null,
                        onNext: phase.allowTopActions
                            ? () async {
                                if (!_tryLockNav()) return;
                                await _ttsCtl.next(
                                  paragraphs: paragraphs,
                                  viewFp: viewFp,
                                  scrollTo: (i) => _storyKey.currentState?.scrollToParagraph(i),
                                );
                              }
                            : null,
                        onTapParagraph: phase.allowTopActions
                            ? (i) async {
                                if (!_tryLockNav()) return;
                                await _ttsCtl.seekTo(
                                  index: i,
                                  paragraphs: paragraphs,
                                  viewFp: viewFp,
                                  scrollTo: (idx) => _storyKey.currentState?.scrollToParagraph(idx),
                                );
                              }
                            : null,
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

                            if (ttsState.playing) {
                              await _ttsCtl.stop(resetToStart: false);
                            }

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
                              if (ttsState.playing) await _ttsCtl.stop(resetToStart: false);
                              await _confirmQuit(context);
                            },
                      icon: const Icon(Icons.exit_to_app),
                      label: const Text('離開'),
                    ),
                  ],
                ),
                if (overlay != null) overlay,
              ],
            );
          },
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
