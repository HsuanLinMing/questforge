// lib/game/game_page_v1.dart
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:questforge_flutter_demo/bridge/bridge_controller_v2.dart';
import 'package:questforge_flutter_demo/bridge/overlay_manager.dart';
import 'package:questforge_flutter_demo/game/widgets/accuse_confirm_sheet_v2.dart';
import 'package:questforge_flutter_demo/voice/accuse_matcher.dart';
import 'package:questforge_flutter_demo/voice/stt_controller.dart';
import 'package:questforge_ui_contract/questforge_contract.dart';

import 'settings/game_settings_repo.dart';
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
  final GameSettingsRepo _settingsRepo = GameSettingsRepo();

  // ---------------------------
  // ✅ STT
  // ---------------------------
  late final SttController _stt = SttController();

  String _heardText = '';
  int? _voiceMatchedIndex; // 可能是人名，也可能是「交給老師」fallback
  bool _voiceConfident = false; // 命中是否偏有把握（命中全名/片段清楚）
  bool _accuseSending = false;

  // ---------------------------
  // ✅ Push-to-talk (按住錄音 / 放開停止)
  // ---------------------------
  bool _pttHolding = false;

  // ---------------------------
  // ✅ Option B: evaluator state
  // ---------------------------
  AccuseEvaluateResponseV2? _accuseEval;
  bool _accuseEvalLoading = false;
  String _accuseEvalError = '';
  Timer? _accuseEvalDebounce;
  int _accuseEvalSeq = 0; // guard stale responses

  static const double _rateMin = 0.85;
  static const double _rateMax = 1.15;
  static const double _rateStep = 0.05;

  // ✅ follow 由 GamePage 管（不塞進 TTS state）
  bool _follow = true;

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
  // TTS playlist (from python)
  // ---------------------------
  Map<String, dynamic>? _extractViewPlaylistCmd(BridgeUiStateV2 state) {
    for (final c in state.commands) {
      final t = c.type.trim();
      final isPlaylist = (t == 'tts_playlist_v1' || t == 'tts_playlist' || t == 'tts_playlist_v2');
      if (!isPlaylist) continue;

      final raw = c.toJson();
      final scope = '${raw['scope'] ?? 'view'}';
      if (scope == 'view') return raw;

      // 有些後端可能沒給 scope，或 scope 不是字串
      if (raw['scope'] == null) return raw;
    }
    return null;
  }

  // 舊 flutter_tts rate (0.35~0.65) → audio speed (0.85~1.15)
  double _mapLegacyTtsRateToAudioSpeed(double legacy) {
    final x = legacy.clamp(0.35, 0.65);
    final t = (x - 0.35) / (0.65 - 0.35); // 0..1
    return (0.85 + t * (1.15 - 0.85)).clamp(0.6, 1.4);
  }

  String _lastDumpFp = '';

  void _debugDumpTtsIfMissing(BridgeUiStateV2 state, NodeView view, String fp, Map<String, dynamic>? playlistCmd) {
    if (playlistCmd != null) return;
    if (_lastDumpFp == fp) return; // 同一個 view 只印一次
    _lastDumpFp = fp;

    final cmdTypes = state.commands.map((e) => e.type).toList();

    // 嘗試直接從 lastRaw 裡看 bundle.view.commands（因為有時 parse 會漏掉）
    final raw = state.lastRaw;
    final bundle = (raw?['bundle'] is Map) ? raw!['bundle'] as Map : null;
    final viewRaw = (bundle?['view'] is Map) ? bundle!['view'] as Map : null;
    final viewCmds = viewRaw?['commands'];

    // ignore: avoid_print
    print('[GamePageV1][TTS_DUMP] fp=$fp node=${view.nodeId}');
    // ignore: avoid_print
    print('[GamePageV1][TTS_DUMP] state.commands types=$cmdTypes');
    // ignore: avoid_print
    final rawBundle = (raw?['bundle'] as Map?)?.cast<String, dynamic>();

    print('[GamePageV1][TTS_DUMP] raw.bundle.view.commands=${(rawBundle?['view'] as Map?)?['commands']}');

    // ✅ 加這行：看 bundle.commands
    print('[GamePageV1][TTS_DUMP] raw.bundle.commands=${rawBundle?['commands']}');
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
  // TTS controller
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
  // node detection
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
    if (_handlingViewChange) return;
    final s = widget.controller.stateVN.value;
    if (_overlayShowingFromState(s)) return;
    if (widget.controller.chooseLockVN.value) return;

    final v = s.view;
    if (v == null) return;
    if (!_isAutoContinueNode(v)) return;

    final idx = v.choices.first.index;
    widget.controller.sendChoose(idx);
  }

  // ---------------------------------------------------------------------------
  // ✅ accuse helpers (voice + kid flow)
  //
  // 目標：
  // - 不管孩子說什麼，都先「接住」：顯示「我聽到你說：xxx」
  // - 能命中就選人名（允許片段：飯糰/波波 也算）
  // - 命中不了就「交給老師」(若 choices 有這個選項)
  // - 送出永遠有下一步：有 heardText 就能送（有 fallback 才能自動送）
  // ---------------------------------------------------------------------------

  void _scheduleAccuseEvaluate(NodeView view, String heard) {
    final text = heard.trim();
    if (text.isEmpty) return;

    // debounce: kids speak in chunks
    _accuseEvalDebounce?.cancel();
    _accuseEvalDebounce = Timer(const Duration(milliseconds: 280), () async {
      if (!mounted) return;
      final currentView = widget.controller.stateVN.value.view;
      if (currentView == null || !_isAccuseNode(currentView)) return;

      final seq = ++_accuseEvalSeq;
      setState(() {
        _accuseEvalLoading = true;
        _accuseEvalError = '';
      });

      try {
        final resp = await widget.controller.accuseEvaluate(
          recognizedText: text,
          nodeId: currentView.nodeId,
        );

        if (!mounted) return;
        if (seq != _accuseEvalSeq) return; // stale

        setState(() {
          _accuseEval = resp;
          _accuseEvalLoading = false;
          _accuseEvalError = '';
        });

        // ✅ Auto-submit (Option B)
        // evaluator 決定 accuse / defer，且 auto_submit=true 時，直接送出
        if (!mounted) return;
        final stillView = widget.controller.stateVN.value.view;
        if (stillView == null || !_isAccuseNode(stillView)) return;

        final auto = (resp.autoSubmit ?? false);
        if (!auto) return;
        if (_accuseSending) return;

        int? idx;
        if (resp.decision == AccuseDecisionV2.accuse) {
          idx = resp.matchedChoiceIndex;
        } else {
          idx = resp.deferChoiceIndex;
        }

        if (idx == null) return;

        // 重要：送出前停止麥克風，避免背景還在聽
        await _stt.stop();

        // 清掉 UI 的 pending 狀態避免看起來卡住
        if (mounted) {
          setState(() {
            _pressedChoiceIndex = idx;
          });
        }

        await _sendAccuseIndexDirect(view: stillView, idx: idx);
      } catch (e) {
        if (!mounted) return;
        if (seq != _accuseEvalSeq) return;

        // fallback: keep UI working
        final local = _bestEffortMatch(currentView, text);
        setState(() {
          _accuseEval = null;
          _accuseEvalLoading = false;
          _accuseEvalError = e.toString();
          _voiceMatchedIndex = local.idx;
          _voiceConfident = local.confident;
        });
      }
    });
  }

  void _clearAccuseVoiceLocal() {
    _accuseEvalDebounce?.cancel();
    _accuseEvalDebounce = null;

    if (_heardText.isNotEmpty || _voiceMatchedIndex != null || _voiceConfident || _accuseEval != null || _accuseEvalError.isNotEmpty) {
      setState(() {
        _heardText = '';
        _voiceMatchedIndex = null;
        _voiceConfident = false;

        _accuseEval = null;
        _accuseEvalLoading = false;
        _accuseEvalError = '';
      });
    }
  }

  // 你常用的「交給老師」文字：我還不確定，交給老師處理（或類似）
  static const List<String> _teacherKeywords = <String>[
    '交給老師',
    '老師',
    '我不確定',
    '不確定',
    '不知道',
    '我不知道',
    '隨便',
    '你決定',
    '想不到',
    '沒想法',
    '先交給',
  ];

  int? _findTeacherFallbackIndex(NodeView view) {
    for (final c in view.choices) {
      final t = c.text.trim();
      for (final k in _teacherKeywords) {
        if (t.contains(k)) return c.index;
      }
    }
    return null;
  }

  ChoiceView? _choiceByIndex(NodeView view, int idx) {
    for (final c in view.choices) {
      if (c.index == idx) return c;
    }
    return null;
  }

  String _norm(String s) {
    // 只保留：中文/英文/數字，去掉空白符號，做簡單容錯
    final lower = s.toLowerCase();
    final cleaned = lower.replaceAll(RegExp(r'\s+'), '');
    return cleaned.replaceAll(RegExp(r'[^\u4e00-\u9fff0-9a-z]+'), '');
  }

  bool _looksLikeTeacherIntent(String recognized) {
    final r = _norm(recognized);
    if (r.isEmpty) return false;
    for (final k in _teacherKeywords) {
      if (r.contains(_norm(k))) return true;
    }
    return false;
  }

  int _lcsLen(String a, String b) {
    // longest common substring length（小字串 OK）
    if (a.isEmpty || b.isEmpty) return 0;
    final n = a.length;
    final m = b.length;
    final dp = List<int>.filled(m + 1, 0);
    var best = 0;
    for (var i = 1; i <= n; i++) {
      var prev = 0;
      for (var j = 1; j <= m; j++) {
        final tmp = dp[j];
        if (a.codeUnitAt(i - 1) == b.codeUnitAt(j - 1)) {
          dp[j] = prev + 1;
          if (dp[j] > best) best = dp[j];
        } else {
          dp[j] = 0;
        }
        prev = tmp;
      }
    }
    return best;
  }

  /// 嘗試用「更寬鬆」的方式命中：
  /// - 先走既有 AccuseMatcher
  /// - 再走「片段」(LCS>=2) / contains
  /// - 回傳 (idx, confident)
  ({int? idx, bool confident}) _bestEffortMatch(NodeView view, String recognized) {
    final raw = recognized.trim();
    if (raw.isEmpty) return (idx: null, confident: false);

    // 1) 先用你原本的 matcher（通常最準）
    final idx0 = AccuseMatcher.matchChoiceIndex(recognized: raw, choices: view.choices);
    if (idx0 != null) return (idx: idx0, confident: true);

    // 2) 如果看起來就是要交給老師
    final teacherIdx = _findTeacherFallbackIndex(view);
    if (_looksLikeTeacherIntent(raw) && teacherIdx != null) {
      return (idx: teacherIdx, confident: true);
    }

    // 3) 寬鬆片段比對（飯糰/波波 之類）
    final r = _norm(raw);
    if (r.isEmpty) return (idx: null, confident: false);

    int? bestIdx;
    double bestScore = 0;
    bool bestConfident = false;

    for (final c in view.choices) {
      final t = _norm(c.text);
      if (t.isEmpty) continue;

      // contains：直接 1.0
      if (t.contains(r) && r.length >= 2) {
        // 例如：r=飯糰，t=飯糰啵啵
        final score = 1.0;
        if (score > bestScore) {
          bestScore = score;
          bestIdx = c.index;
          bestConfident = true;
        }
        continue;
      }
      if (r.contains(t) && t.length >= 2) {
        // 例如：r=我覺得是飯糰啵啵，t=飯糰啵啵
        final score = 1.0;
        if (score > bestScore) {
          bestScore = score;
          bestIdx = c.index;
          bestConfident = true;
        }
        continue;
      }

      // LCS：>=2 視為有可能（孩子常只講片段）
      final l = _lcsLen(r, t);
      if (l >= 2) {
        // 分數偏向「片段佔 choice 的比例」
        final base = l / (t.length <= 0 ? 1 : t.length);
        // 略加成：片段越長越有把握
        final score = base + (l >= 3 ? 0.25 : 0.12);
        if (score > bestScore) {
          bestScore = score;
          bestIdx = c.index;
          bestConfident = l >= 3 || score >= 0.55;
        }
      }
    }

    // 4) 沒命中：先不強配（交給 fallback）
    if (bestIdx == null) return (idx: null, confident: false);

    // 如果分數太低，也不算命中（避免亂指）
    if (bestScore < 0.45) return (idx: null, confident: false);

    return (idx: bestIdx, confident: bestConfident);
  }

  Future<void> _pttStart(NodeView view, {required bool ttsPlaying}) async {
    if (_pttHolding) return;
    if (!mounted) return;

    setState(() => _pttHolding = true);

    // 開始說前：停掉 TTS，避免同時播音 + 收音
    if (ttsPlaying) {
      await _ttsCtl.stop(resetToStart: false);
    }

    // 開始說前：清掉上一句（你想保留也可以拿掉這行）
    _clearAccuseVoiceLocal();

    // 若已在聽，先停掉
    if (_stt.vn.value.listening) {
      await _stt.stop();
    }

    // ✅ 進入「一直聽」模式：靠放開來 stop
    // 你目前 start 只有 listenFor 參數，所以用很長的時間即可。
    // 若你的 SttController 已支援 listenOnce/autoStopOnFinal，建議在那邊預設關掉自動停。
    await _stt.startHoldToTalk();
  }

  Future<void> _pttStop() async {
    if (!_pttHolding) return;
    if (!mounted) return;

    // ✅ 先把 holding 關掉，避免下面 listener/狀態又觸發其他事
    setState(() => _pttHolding = false);

    await _stt.stop();

    // ✅ 很重要：Android 常常 stop 之後才補 finalResult
    await Future.delayed(const Duration(milliseconds: 90));
    if (!mounted) return;

    final v = widget.controller.stateVN.value.view;
    if (v == null || !_isAccuseNode(v)) return;

    final incomingFinal = _stt.vn.value.finalText.trim();
    if (incomingFinal.isEmpty) return;

    _applyAccuseHeardText(v, incomingFinal);
  }

  void _applyAccuseHeardText(NodeView view, String recognized) {
    final raw = recognized.trim();
    if (raw.isEmpty) return;

    // ✅ Option B: always accept heard text, evaluator decides whether to accuse or defer.
    setState(() {
      _heardText = raw;
      // keep old local matching as fallback only
      _voiceMatchedIndex = null;
      _voiceConfident = false;
    });

    _scheduleAccuseEvaluate(view, raw);
  }

  String _buildFifiEcho({
    required String heard,
    required String? selectedName,
    required bool isTeacher,
    required bool confident,
  }) {
    final h = heard.trim();
    if (h.isEmpty) return '菲菲：我剛剛沒有聽清楚耶～你可以再說一次，或直接點下面的選項喔！';

    if (selectedName == null) {
      return '菲菲：我聽到你說「$h」。這個想法很重要～但我還不太確定你要選誰。你可以再說一次，或直接點下面的選項。';
    }

    if (isTeacher) {
      return '菲菲：我聽到你說「$h」。我還不太確定你要選誰，那我們先交給老師，一起把看到的再整理清楚。';
    }

    if (confident) {
      return '菲菲：我聽到你說「$h」。你是覺得可能跟「$selectedName」有關，對嗎？那我們先選 $selectedName，看看老師怎麼說。';
    }

    return '菲菲：我聽到你說「$h」。我猜你可能在說「$selectedName」，但如果不確定也沒關係，我們可以交給老師一起想。';
  }

  Future<void> _sendAccuseIndex({
    required NodeView view,
    required int idx,
    required String displayText,
    String? heard,
  }) async {
    if (_accuseSending) return;
    setState(() => _accuseSending = true);
    try {
      final ok = await showModalBottomSheet<bool>(
        context: context,
        useSafeArea: true,
        isScrollControlled: false,
        builder: (ctx) {
          return AccuseConfirmSheetV2(
            heard: (heard ?? '').trim().isEmpty ? null : heard!.trim(),
            selectedName: displayText,
            onCancel: () => Navigator.of(ctx).pop(false),
            onConfirm: () => Navigator.of(ctx).pop(true),
          );
        },
      );

      if (ok == true && mounted) {
        widget.controller.sendChoose(idx);
      }
    } finally {
      if (mounted) setState(() => _accuseSending = false);
    }
  }

  Future<void> _sendAccuseIndexDirect({
    required NodeView view,
    required int idx,
  }) async {
    if (_accuseSending) return;
    setState(() => _accuseSending = true);
    try {
      widget.controller.sendChoose(idx);
    } finally {
      if (mounted) setState(() => _accuseSending = false);
    }
  }

  // ---------------------------
  // lifecycle
  // ---------------------------
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);

    _ttsCtl.onNarrationEnd = () {
      if (!mounted) return;
      Future.microtask(_tryAutoContinueAfterTtsEnd);
    };

    // ✅ init TTS
    // ignore: discarded_futures
    _ttsCtl.init();

    // ✅ init STT
    // ignore: discarded_futures
    _stt.init(preferredLocaleId: 'zh_TW');

    // ✅ 載入記憶語速
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final legacy = await _settingsRepo.loadTtsRate(fallback: 0.45);
      final speed = _mapLegacyTtsRateToAudioSpeed(legacy);
      await _ttsCtl.setRate(speed);
    });
  }

  Future<void> _openStoryMenuSheet({
    required List<StoryParagraph> paragraphs,
    required String viewFp,
    required TtsPlaybackState ttsState,
  }) async {
    if (!mounted) return;

    final cs = Theme.of(context).colorScheme;

    await showModalBottomSheet<void>(
      context: context,
      useSafeArea: true,
      builder: (ctx) {
        return StatefulBuilder(
          builder: (ctx, setSheetState) {
            final rate = _ttsCtl.vn.value.rate;

            Future<void> setRate(double next) async {
              final clamped = next.clamp(_rateMin, _rateMax);
              await _ttsCtl.setRate(clamped);
              await _settingsRepo.saveTtsRate(clamped);
              setSheetState(() {});
            }

            Future<void> replay() async {
              if (!_tryLockNav()) return;
              await _ttsCtl.replayCurrent(
                paragraphs: paragraphs,
                viewFp: viewFp,
                scrollTo: (i) => _storyKey.currentState?.scrollToParagraph(i),
              );
              setSheetState(() {});
            }

            void toggleFollow() {
              setState(() => _follow = !_follow);
              setSheetState(() {});
            }

            return Padding(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 44,
                    height: 5,
                    decoration: BoxDecoration(
                      color: cs.outlineVariant,
                      borderRadius: BorderRadius.circular(999),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Text(
                        '功能選單',
                        style: Theme.of(ctx).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w900),
                      ),
                      const Spacer(),
                      IconButton(onPressed: () => Navigator.of(ctx).pop(), icon: const Icon(Icons.close)),
                    ],
                  ),
                  const SizedBox(height: 8),
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.replay),
                    title: const Text('重播本段'),
                    subtitle: Text('從段落 ${(_ttsCtl.activeParagraphIndex + 1)} 開始'),
                    onTap: replay,
                  ),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    secondary: Icon(_follow ? Icons.my_location : Icons.location_disabled),
                    title: const Text('跟隨段落'),
                    subtitle: const Text('播放時自動捲動到目前段落'),
                    value: _follow,
                    onChanged: (_) => toggleFollow(),
                  ),
                  const Divider(),
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.speed),
                    title: const Text('語速'),
                    subtitle: Text('目前：${rate.toStringAsFixed(2)}x'),
                    trailing: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        IconButton(
                          tooltip: '放慢',
                          onPressed: () => setRate(rate - _rateStep),
                          icon: const Icon(Icons.remove_circle_outline),
                        ),
                        IconButton(
                          tooltip: '加快',
                          onPressed: () => setRate(rate + _rateStep),
                          icon: const Icon(Icons.add_circle_outline),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
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

    _stt.dispose();

    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) async {
    final inactive = state == AppLifecycleState.inactive || state == AppLifecycleState.paused;

    if (inactive) {
      _appInactive = true;

      await _ttsCtl.stop(resetToStart: false);
      await _stt.stop();

      if (mounted) {
        Navigator.of(context, rootNavigator: true).popUntil((r) => r.isFirst);
      }

      _pressedClearTimer?.cancel();
      _pressedClearTimer = null;
      _cancelSendingWatchdog();

      if (mounted) {
        setState(() => _pressedChoiceIndex = null);
        _clearAccuseVoiceLocal();
      }
      return;
    }

    if (state == AppLifecycleState.resumed) {
      _appInactive = false;

      FocusManager.instance.primaryFocus?.unfocus();
      try {
        await SystemChannels.textInput.invokeMethod('TextInput.hide');
      } catch (_) {}

      await _ttsCtl.stop(resetToStart: false);
      await _stt.stop();

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

  void _scheduleHandleViewChanged(NodeView view, List<StoryParagraph> paragraphs, {required Map<String, dynamic>? playlistCmd}) {
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

        // ✅ view change：清掉本地 voice 狀態 & 停止 mic（避免跳節點殘留/背景聽）
        await _stt.stop();
        _clearAccuseVoiceLocal();

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
          playlistCmd: playlistCmd,
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

  String _sttUserError(String raw) {
    final e = raw.trim().toLowerCase();
    if (e.isEmpty) return '';
    if (e.contains('error_no_match')) return ''; // ✅ 不顯示
    if (e.contains('error_speech_timeout')) return ''; // ✅ 不顯示
    return raw;
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

        // ✅ 從 commands 拿 tts_playlist_v1 (scope=view)
        final playlistCmd = _extractViewPlaylistCmd(state);
        _debugDumpTtsIfMissing(state, view, viewFp, playlistCmd);

        _scheduleHandleViewChanged(view, paragraphs, playlistCmd: playlistCmd);

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
          onCloseAsk: widget.controller.clearAskOverlayLocal,
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
          onCloseEnd: widget.controller.clearEndOverlayLocal,
        );

        final mq = MediaQuery.of(context);
        final narrationScaled = mq.copyWith(textScaler: TextScaler.linear(_fontScale));

        final isAccuse = _isAccuseNode(view);

        return ValueListenableBuilder<TtsPlaybackState>(
          valueListenable: _ttsCtl.vn,
          builder: (context, ttsState, __) {
            final activeNow = paragraphs.isEmpty ? 0 : ttsState.activeParagraphIndex.clamp(0, paragraphs.length - 1);

            return Stack(
              children: [
                ListView(
                  key: _pageRebuildKey,
                  physics: _pttHolding ? const NeverScrollableScrollPhysics() : null,
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
                        activeIndex: activeNow,
                        isPlaying: ttsState.playing,
                        ttsReady: ttsState.ready,
                        scrollEnabled: phase.allowStoryScroll,
                        rate: ttsState.rate,
                        onOpenMenu: phase.allowTopActions
                            ? () => _openStoryMenuSheet(
                                  paragraphs: paragraphs,
                                  viewFp: viewFp,
                                  ttsState: ttsState,
                                )
                            : null,
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

                    // ✅ accuse voice block (real STT + 接住孩子)
                    if (isAccuse) ...[
                      const SizedBox(height: 10),
                      const AccusePanel(
                        title: '最後推理',
                        hint: '你可以用說的，或直接點一下。',
                      ),
                      const SizedBox(height: 10),
                      ValueListenableBuilder<SttState>(
                        valueListenable: _stt.vn,
                        builder: (context, sttState, _) {
                          final listening = sttState.listening;
                          final available = sttState.available;
                          final userErr = _sttUserError(sttState.error);

                          final teacherIdx = _findTeacherFallbackIndex(view);

                          // ------------------------------------------------------------
                          // Option B: evaluator-driven
                          // - Always "catch" child's speech.
                          // - Evaluator decides accuse vs defer_to_teacher.
                          // - If evaluator fails, fallback to local best-effort match.
                          // ------------------------------------------------------------
                          int? resolvedIdx;
                          final eval = _accuseEval;

                          if (_heardText.isNotEmpty && eval != null) {
                            if (eval.decision == AccuseDecisionV2.accuse) {
                              resolvedIdx = eval.matchedChoiceIndex;
                            } else {
                              resolvedIdx = eval.deferChoiceIndex ?? teacherIdx;
                            }
                          }

// fallback: local matching
                          resolvedIdx ??= _voiceMatchedIndex;

// final fallback: teacher (should exist in accuse nodes)
                          if (_heardText.isNotEmpty) {
                            resolvedIdx ??= teacherIdx;
                          }

                          final resolvedChoice = (resolvedIdx == null) ? null : _choiceByIndex(view, resolvedIdx!);
                          final isTeacher = teacherIdx != null && resolvedIdx == teacherIdx;

// ✅ 不要在 evaluator loading 時就送（避免先送 teacher）
                          final canSubmit =
                              phase.allowChoiceTap && !_accuseSending && !_accuseEvalLoading && _heardText.isNotEmpty && resolvedIdx != null;

                          final fifi = (eval != null && eval.fifiReply.trim().isNotEmpty)
                              ? eval.fifiReply
                              : _buildFifiEcho(
                                  heard: _heardText,
                                  selectedName: resolvedChoice?.text,
                                  isTeacher: isTeacher,
                                  confident: _voiceConfident && !isTeacher,
                                );

                          return Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: Theme.of(context).colorScheme.surface,
                              borderRadius: BorderRadius.circular(14),
                              border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  '用說的回答',
                                  style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
                                ),
                                const SizedBox(height: 6),
                                Text(
                                  available ? '按下麥克風，說出你覺得是誰（也可以說：交給老師）' : '語音辨識尚未就緒（請確認麥克風/語音辨識權限）',
                                  style: Theme.of(context).textTheme.bodySmall,
                                ),

                                if (userErr.isNotEmpty) ...[
                                  const SizedBox(height: 6),
                                  Text('（語音錯誤）$userErr', style: Theme.of(context).textTheme.bodySmall),
                                ],
                                const SizedBox(height: 10),
                                Row(
                                  children: [
                                    Expanded(
                                      child: IgnorePointer(
                                        ignoring: (!available || _accuseSending || !phase.allowChoiceTap),
                                        child: Opacity(
                                          opacity: (!available || _accuseSending || !phase.allowChoiceTap) ? 0.45 : 1,
                                          child: Listener(
                                            behavior: HitTestBehavior.opaque,
                                            onPointerDown: (_) async {
                                              final v = widget.controller.stateVN.value.view;
                                              if (v == null) return;
                                              if (!_isAccuseNode(v)) return;
                                              await _pttStart(v, ttsPlaying: ttsState.playing);
                                            },
                                            onPointerUp: (_) async => _pttStop(),
                                            onPointerCancel: (_) async => _pttStop(),
                                            child: Container(
                                              height: 44,
                                              decoration: BoxDecoration(
                                                color: (_pttHolding || listening) ? Colors.deepPurple.shade700 : Colors.deepPurple,
                                                borderRadius: BorderRadius.circular(999),
                                              ),
                                              child: Row(
                                                mainAxisAlignment: MainAxisAlignment.center,
                                                children: [
                                                  Icon((_pttHolding || listening) ? Icons.mic : Icons.mic_none, color: Colors.white),
                                                  const SizedBox(width: 8),
                                                  Text(
                                                    (_pttHolding || listening) ? '錄音中…（放開停止）' : '按住說話',
                                                    style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700),
                                                  ),
                                                ],
                                              ),
                                            ),
                                          ),
                                        ),
                                      ),
                                    ),
                                    const SizedBox(width: 10),
                                    OutlinedButton(
                                      onPressed: (_accuseSending || !phase.allowChoiceTap)
                                          ? null
                                          : () async {
                                              await _pttStop();
                                              await _stt.cancel();
                                              if (!mounted) return;
                                              _clearAccuseVoiceLocal();
                                            },
                                      child: const Text('重來'),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 10),

// evaluator status
                                if (_heardText.isNotEmpty) ...[
                                  if (_accuseEvalLoading) ...[
                                    Row(
                                      children: [
                                        const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
                                        const SizedBox(width: 8),
                                        Text('菲菲正在幫你整理…', style: Theme.of(context).textTheme.bodySmall),
                                      ],
                                    ),
                                    const SizedBox(height: 8),
                                  ] else if (_accuseEvalError.isNotEmpty) ...[
                                    Text('（AI 判斷暫時失敗，先用本地比對）$_accuseEvalError', style: Theme.of(context).textTheme.bodySmall),
                                    const SizedBox(height: 8),
                                  ] else if (_accuseEval != null) ...[
                                    Text(
                                      '（AI 分數：${_accuseEval!.score.toStringAsFixed(2)} / 門檻：${_accuseEval!.threshold.toStringAsFixed(2)}）',
                                      style: Theme.of(context).textTheme.bodySmall,
                                    ),
                                    const SizedBox(height: 8),
                                  ],
                                ],

                                SizedBox(
                                  width: double.infinity,
                                  child: FilledButton(
                                    onPressed: canSubmit
                                        ? () => _sendAccuseIndex(
                                              view: view,
                                              idx: resolvedIdx!,
                                              displayText: resolvedChoice?.text ?? '交給老師',
                                              heard: _heardText,
                                            )
                                        : null,
                                    child: Text(_accuseSending
                                        ? '送出中…'
                                        : (_heardText.isEmpty
                                            ? '先說一句話再送出'
                                            : (resolvedChoice == null ? '請再說一次或點選' : (isTeacher ? '送出（交給老師）' : '送出這個答案')))),
                                  ),
                                ),
                              ],
                            ),
                          );
                        },
                      ),
                    ],

                    const SizedBox(height: 14),

                    // choices
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

                            // ✅ accuse：先停麥克風，避免同時輸入
                            if (isAccuse) {
                              await _stt.stop();
                            }

                            _setPressedChoice(c.index);
                            _onChoiceTapHook(c);

                            if (isAccuse) {
                              // 點選：也走同一套確認（但不需要 heard）
                              setState(() {
                                _heardText = '';
                                _voiceMatchedIndex = c.index;
                                _voiceConfident = true;
                              });
                              await _sendAccuseIndex(
                                view: view,
                                idx: c.index,
                                displayText: c.text,
                                heard: null,
                              );
                              return;
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
                              await _stt.stop();
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
