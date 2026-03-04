// lib/bridge/bridge_controller_v2.dart
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:questforge_flutter_demo/fastapi_bridge.dart';
import 'package:questforge_ui_contract/questforge_contract.dart';

import 'command_router.dart';
import 'debug_snapshot.dart';
import 'fastapi_sender.dart';

@immutable
class BridgeUiStateV2 {
  final NodeView? view;
  final List<CommandV2> commands;
  final CommandBundle bundle;

  final Map<String, dynamic>? lastRaw;
  final DebugSnapshotV2 snapshot;

  const BridgeUiStateV2({
    required this.view,
    required this.commands,
    required this.bundle,
    required this.lastRaw,
    required this.snapshot,
  });

  BridgeUiStateV2 copyWith({
    NodeView? view,
    List<CommandV2>? commands,
    CommandBundle? bundle,
    Map<String, dynamic>? lastRaw,
    DebugSnapshotV2? snapshot,
  }) {
    return BridgeUiStateV2(
      view: view ?? this.view,
      commands: commands ?? this.commands,
      bundle: bundle ?? this.bundle,
      lastRaw: lastRaw ?? this.lastRaw,
      snapshot: snapshot ?? this.snapshot,
    );
  }

  String? get currentStoryId {
    try {
      final v = lastRaw?['bundle']?['view'];
      if (v is Map) {
        return v['runtime']?['story']?['story_id']?.toString();
      }
    } catch (_) {}
    return null;
  }

  String? get currentStorySource {
    try {
      final v = lastRaw?['bundle']?['view'];
      if (v is Map) {
        return v['runtime']?['story']?['source']?.toString();
      }
    } catch (_) {}
    return null;
  }

  static BridgeUiStateV2 empty() {
    final snap = DebugSnapshotV2(
      nodeId: '',
      isOver: false,
      cmdTypes: const <String>[],
      endActionLocked: false,
      pendingEndActionId: null,
      chooseLocked: false,
      pendingChoiceIndex: null,
      lastRawClip: null,
      lastAck: null,
    );
    return BridgeUiStateV2(
      view: null,
      commands: const <CommandV2>[],
      bundle: const CommandBundle(),
      lastRaw: null,
      snapshot: snap,
    );
  }
}

/// raw command map 包成 CommandV2
class WireCommandV2 implements CommandV2 {
  WireCommandV2(this._raw);
  final Map<String, dynamic> _raw;

  @override
  String get type => (_raw['type'] ?? '').toString();

  @override
  Map<String, dynamic> toJson() => _raw;
}

class BridgeControllerV2 {
  BridgeControllerV2({
    required FastApiBridge api,
    required String Function(Object? kind) kindToWire,
    CommandRouterV2 router = const CommandRouterV2(),
    Duration endActionTimeout = const Duration(seconds: 5),
    Duration chooseActionTimeout = const Duration(seconds: 5),
  })  : _api = api,
        _router = router,
        _kindToWire = kindToWire,
        _endActionTimeoutDur = endActionTimeout,
        _chooseTimeoutDur = chooseActionTimeout {
    stateVN.value = BridgeUiStateV2.empty();

    sender = BridgeSenderApi(
      api,
      onStep: _handleSenderStep,
      onError: _handleSenderError,
    );
  }

  final FastApiBridge _api;
  final CommandRouterV2 _router;
  final String Function(Object? kind) _kindToWire;

  late final BridgeSenderApi sender;

  final ValueNotifier<BridgeUiStateV2> stateVN =
      ValueNotifier<BridgeUiStateV2>(BridgeUiStateV2.empty());

  bool _started = false;

  // ------------------------------------------------------------
  // EndScreen lock/unlock
  // ------------------------------------------------------------
  final ValueNotifier<bool> endActionLockVN = ValueNotifier<bool>(false);
  final ValueNotifier<String?> pendingEndActionIdVN =
      ValueNotifier<String?>(null);

  final Duration _endActionTimeoutDur;
  Timer? _endActionTimeoutTimer;

  // ------------------------------------------------------------
  // choose lock/unlock
  // ------------------------------------------------------------
  final ValueNotifier<bool> chooseLockVN = ValueNotifier<bool>(false);
  final ValueNotifier<int?> pendingChoiceIndexVN = ValueNotifier<int?>(null);

  final Duration _chooseTimeoutDur;
  Timer? _chooseTimeoutTimer;

  bool get isStarted => _started;
  bool get endActionLocked => endActionLockVN.value;
  bool get chooseLocked => chooseLockVN.value;

  /// ✅ 給 TTS controller 用：查目前 view 的 playlist readiness
  Future<Map<String, dynamic>?> fetchTtsStatusCmd({
    required String viewFp,
    required int count,
  }) =>
      _api.fetchTtsStatusCmd(viewFp: viewFp, count: count);

  /// ✅ 給 TTS controller 用：polling 段落是否生成完成
  Future<TtsStatus> fetchTtsStatus(
          {required String viewFp, required int count}) =>
      _api.fetchTtsStatus(viewFp: viewFp, count: count);

  bool get isUiBlocked {
    final b = stateVN.value.bundle;
    return b.end != null || b.ask != null || b.quiz != null;
  }

  // ------------------------------------------------------------
  // lifecycle
  // ------------------------------------------------------------
  void start() {
    if (_started) return;
    _started = true;
    unawaited(_startNewSession());
  }

  void stop() {
    _started = false;

    _endActionTimeoutTimer?.cancel();
    _endActionTimeoutTimer = null;

    _chooseTimeoutTimer?.cancel();
    _chooseTimeoutTimer = null;
  }

  void dispose() {
    stop();
    stateVN.dispose();
    endActionLockVN.dispose();
    pendingEndActionIdVN.dispose();
    chooseLockVN.dispose();
    pendingChoiceIndexVN.dispose();
  }

  Future<void> _startNewSession() async {
    try {
      final r = await _api.start();
      _applyApiBundle(
        bundle: r.bundle,
        isOver: r.isOver,
        raw: <String, dynamic>{
          'type': 'api_start',
          'session_id': r.sessionId,
          'bundle': r.bundle,
          'events': r.events,
          'is_over': r.isOver,
        },
      );
    } catch (e, st) {
      debugPrint('[BridgeControllerV2] start failed: $e\n$st');
      _updateStateRawOnly(<String, dynamic>{
        'type': 'api_start_error',
        'error': e.toString(),
      });
    }
  }

  // ------------------------------------------------------------
  // EndScreen lock/unlock
  // ------------------------------------------------------------
  void lockEndAction(String actionId, {String? pendingLabel}) {
    pendingEndActionIdVN.value = pendingLabel ?? actionId;
    endActionLockVN.value = true;

    _endActionTimeoutTimer?.cancel();
    _endActionTimeoutTimer = Timer(_endActionTimeoutDur, unlockEndAction);

    _refreshSnapshotOnly();
  }

  void unlockEndAction() {
    _endActionTimeoutTimer?.cancel();
    _endActionTimeoutTimer = null;

    pendingEndActionIdVN.value = null;
    endActionLockVN.value = false;

    _refreshSnapshotOnly();
  }

  // ------------------------------------------------------------
  // choose lock/unlock
  // ------------------------------------------------------------
  void lockChoose(int index) {
    pendingChoiceIndexVN.value = index;
    chooseLockVN.value = true;

    _chooseTimeoutTimer?.cancel();
    _chooseTimeoutTimer = Timer(_chooseTimeoutDur, unlockChoose);

    _refreshSnapshotOnly();
  }

  void unlockChoose() {
    _chooseTimeoutTimer?.cancel();
    _chooseTimeoutTimer = null;

    pendingChoiceIndexVN.value = null;
    chooseLockVN.value = false;

    _refreshSnapshotOnly();
  }

  void clearAskOverlayLocal() {
    final old = stateVN.value;
    if (old.bundle.ask == null) return;
    stateVN.value = old.copyWith(bundle: old.bundle.copyWith(ask: null));
    _refreshSnapshotOnly();
  }

  void clearEndOverlayLocal() {
    final old = stateVN.value;
    if (old.bundle.end == null) return;
    stateVN.value = old.copyWith(bundle: old.bundle.copyWith(end: null));
    _refreshSnapshotOnly();
  }

  void _refreshSnapshotOnly() {
    final old = stateVN.value;
    final snap = old.snapshot.copyWith(
      endActionLocked: endActionLockVN.value,
      pendingEndActionId: pendingEndActionIdVN.value,
      chooseLocked: chooseLockVN.value,
      pendingChoiceIndex: pendingChoiceIndexVN.value,
    );
    stateVN.value = old.copyWith(snapshot: snap);
  }

  // ------------------------------------------------------------
  // Public send APIs
  // ------------------------------------------------------------
  bool sendChoose(int index) {
    if (chooseLockVN.value) return false;
    if (isUiBlocked) return false;

    lockChoose(index);

    unawaited(() async {
      try {
        final r = await _api.choose(choiceIndex: index);

        unlockEndAction();
        unlockChoose();

        _applyApiBundle(
          bundle: r.bundle,
          isOver: r.isOver,
          raw: <String, dynamic>{
            'type': 'api_choose',
            'choice_index': index,
            'bundle': r.bundle,
            'events': r.events,
            'is_over': r.isOver,
          },
        );
      } catch (e, st) {
        debugPrint('[BridgeControllerV2] choose failed: $e\n$st');
        unlockChoose();
        _updateStateRawOnly(<String, dynamic>{
          'type': 'api_choose_error',
          'choice_index': index,
          'error': e.toString(),
        });
      }
    }());

    return true;
  }

  bool sendReplay() {
    if (chooseLockVN.value) return false;
    if (isUiBlocked) return false;

    lockChoose(-1);

    unawaited(() async {
      try {
        final r = await _api.replay();

        unlockEndAction();
        unlockChoose();

        _applyApiBundle(
          bundle: r.bundle,
          isOver: r.isOver,
          raw: <String, dynamic>{
            'type': 'api_replay',
            'bundle': r.bundle,
            'events': r.events,
            'is_over': r.isOver,
          },
        );
      } catch (e, st) {
        debugPrint('[BridgeControllerV2] replay failed: $e\n$st');
        unlockChoose();
        _updateStateRawOnly(<String, dynamic>{
          'type': 'api_replay_error',
          'error': e.toString(),
        });
      }
    }());

    return true;
  }

  bool sendEndActionSpec(UiActionSpecV2 action) {
    if (endActionLockVN.value) return false;

    clearEndOverlayLocal();

    final id = (action.id ?? '').toString().trim();
    final wireKind = _kindToWire(action.kind).trim().isEmpty
        ? 'end_flow'
        : _kindToWire(action.kind).trim();

    if (wireKind != 'end_flow') {
      debugPrint(
          '[BridgeControllerV2] end action ignored: wireKind=$wireKind id=$id');
      return false;
    }

    final actionId = '$wireKind/$id';
    lockEndAction(actionId, pendingLabel: action.text);

    final String? oldStoryId = stateVN.value.currentStoryId;
    final String? oldSource = stateVN.value.currentStorySource;
    final bool isFinishedStory =
        (id == 'switch_case' || id == 'restart_case' || id == 'quit');

    unawaited(() async {
      try {
        final r = await _api.endFlow(endAction: id);

        // 如果之前的還是 ai 而且我們換案件了，把舊的刪了
        if (isFinishedStory &&
            oldSource == 'ai' &&
            oldStoryId != null &&
            oldStoryId.isNotEmpty) {
          debugPrint('[BridgeControllerV2] cleaning up AI story: $oldStoryId');
          _api.cleanupAiStory(oldStoryId).ignore();
        }

        unlockEndAction();
        unlockChoose();

        _applyApiBundle(
          bundle: r.bundle,
          isOver: r.isOver,
          raw: <String, dynamic>{
            'type': 'api_end_flow',
            'end_action': id,
            'bundle': r.bundle,
            'events': r.events,
            'is_over': r.isOver,
          },
        );
      } catch (e, st) {
        debugPrint('[BridgeControllerV2] end_flow failed: $e\n$st');
        unlockEndAction();
        _updateStateRawOnly(<String, dynamic>{
          'type': 'api_end_flow_error',
          'end_action': id,
          'error': e.toString(),
        });
      }
    }());

    return true;
  }

  bool sendSetReasons({required List<String> reasonIds, String text = ''}) {
    if (chooseLockVN.value) return false;
    lockChoose(-2);
    sender.sendSetReasons(reasonIds: reasonIds, text: text);
    return true;
  }

  bool sendConfirmQuiz(List<Object?> answers, {bool skipped = false}) {
    if (chooseLockVN.value) return false;
    lockChoose(-3);
    sender.sendConfirmQuizAnswerList(answers, skipped: skipped);
    return true;
  }

  // ------------------------------------------------------------
  // sender callbacks
  // ------------------------------------------------------------
  void _handleSenderStep(
    GameStepResp r, {
    required String type,
    Map<String, dynamic>? extra,
  }) {
    unlockEndAction();
    unlockChoose();

    _applyApiBundle(
      bundle: r.bundle,
      isOver: r.isOver,
      raw: <String, dynamic>{
        'type': type,
        if (extra != null) ...extra,
        'bundle': r.bundle,
        'events': r.events,
        'is_over': r.isOver,
      },
    );
  }

  void _handleSenderError(
    Object e,
    StackTrace st, {
    required String type,
    Map<String, dynamic>? extra,
  }) {
    debugPrint('[BridgeControllerV2] sender failed ($type): $e\n$st');
    unlockEndAction();
    unlockChoose();
    _updateStateRawOnly(<String, dynamic>{
      'type': '${type}_error',
      if (extra != null) ...extra,
      'error': e.toString(),
    });
  }

  // ------------------------------------------------------------
  // Option B: Accuse evaluator
  // ------------------------------------------------------------
  Future<AccuseEvaluateResponseV2> accuseEvaluate({
    required String recognizedText,
    String? nodeId,
  }) {
    return _api.accuseEvaluate(recognizedText: recognizedText, nodeId: nodeId);
  }

  // ------------------------------------------------------------
  // apply API bundle -> BridgeUiStateV2
  // ------------------------------------------------------------
  void _applyApiBundle({
    required Map<String, dynamic> bundle,
    required Map<String, dynamic> raw,
    bool? isOver,
  }) {
    final viewJson = bundle['view'];
    final NodeView? view = (viewJson is Map)
        ? NodeView.fromJson(Map<String, dynamic>.from(viewJson.cast()))
        : null;

    final commands = _commandsFromBundle(bundle);
    final parsedBundle = _router.parse(commands);
    final inferredNodeId = _inferNodeIdFromCommands(commands);

    final snap = DebugSnapshotV2(
      nodeId: view?.nodeId ?? inferredNodeId,
      isOver: isOver ?? false,
      cmdTypes: commands.map((e) => e.type).toList(),
      endActionLocked: endActionLockVN.value,
      pendingEndActionId: pendingEndActionIdVN.value,
      chooseLocked: chooseLockVN.value,
      pendingChoiceIndex: pendingChoiceIndexVN.value,
      lastRawClip: _clipRaw(raw),
      lastAck: stateVN.value.snapshot.lastAck,
    );

    stateVN.value = stateVN.value.copyWith(
      view: view,
      commands: commands,
      bundle: parsedBundle,
      lastRaw: raw,
      snapshot: snap,
    );

    // ✅ Debug: 每次 bundle apply 都印出故事來源，方便驗證 sample → AI 切換
    debugPrint(
      '[QF] story source=${stateVN.value.currentStorySource ?? "-"} '
      'id=${stateVN.value.currentStoryId ?? "-"} '
      'node=${stateVN.value.view?.nodeId ?? "-"}',
    );
  }

  void _updateStateRawOnly(Map<String, dynamic> raw) {
    final old = stateVN.value;
    final snap = old.snapshot.copyWith(
      endActionLocked: endActionLockVN.value,
      pendingEndActionId: pendingEndActionIdVN.value,
      chooseLocked: chooseLockVN.value,
      pendingChoiceIndex: pendingChoiceIndexVN.value,
      lastRawClip: _clipRaw(raw),
    );
    stateVN.value = old.copyWith(lastRaw: raw, snapshot: snap);
  }

  Map<String, dynamic> _clipRaw(Map<String, dynamic> raw) {
    final out = <String, dynamic>{};
    out['type'] = (raw['type'] ?? '').toString();
    if (raw.containsKey('session_id')) out['session_id'] = raw['session_id'];
    if (raw.containsKey('choice_index'))
      out['choice_index'] = raw['choice_index'];
    if (raw.containsKey('end_action')) out['end_action'] = raw['end_action'];

    final b = raw['bundle'];
    if (b is Map) {
      final bm = Map<String, dynamic>.from(b.cast<String, dynamic>());

      final cmds0 = bm['commands'];
      if (cmds0 is List) out['bundle_commands_count'] = cmds0.length;

      final v = bm['view'];
      if (v is Map) {
        final vm = Map<String, dynamic>.from(v.cast<String, dynamic>());
        out['view'] = <String, dynamic>{
          'nodeId': vm['nodeId'],
          'title': vm['title'],
          'choices_count':
              (vm['choices'] is List) ? (vm['choices'] as List).length : null,
        };
        final vcmds = vm['commands'];
        if (vcmds is List) out['view_commands_count'] = vcmds.length;
      }

      out['hasAsk'] = bm['ask'] != null;
      out['hasQuiz'] = bm['quiz'] != null;
      out['hasEnd'] = bm['end'] != null;
    }

    final ev = raw['events'];
    if (ev is List) {
      out['events_count'] = ev.length;
      out['events_head'] = ev.isNotEmpty ? ev.first : null;
    }
    out['is_over'] = raw['is_over'];

    return out;
  }

  // ------------------------------------------------------------
  // Commands decode (bundle.commands + view.commands + ask/quiz/end)
  // ------------------------------------------------------------
  List<CommandV2> _commandsFromBundle(Map<String, dynamic> bundle) {
    final out = <CommandV2>[];

    void addIfMap(dynamic v) {
      if (v is Map)
        out.add(WireCommandV2(
            Map<String, dynamic>.from(v.cast<String, dynamic>())));
    }

    void addIfMapList(dynamic v) {
      if (v is! List) return;
      for (final it in v) {
        if (it is Map) {
          out.add(WireCommandV2(
              Map<String, dynamic>.from(it.cast<String, dynamic>())));
        }
      }
    }

    // 1) bundle.commands（新版）
    addIfMapList(bundle['commands']);

    // 2) view.commands（也吃，方便兼容/除錯）
    final view = bundle['view'];
    if (view is Map) {
      addIfMapList(view['commands']);
    }

    // 3) 舊版 ask/quiz/end
    addIfMap(bundle['ask']);
    addIfMap(bundle['quiz']);
    addIfMap(bundle['end']);

    return out;
  }

  String _inferNodeIdFromCommands(List<CommandV2> commands) {
    for (final c in commands) {
      final raw = c.toJson();
      final nid = (raw['node_id'] ?? raw['nodeId'] ?? raw['meta']?['node_id'])
          ?.toString()
          .trim();
      if (nid != null && nid.isNotEmpty) return nid;
    }
    return '';
  }
}
