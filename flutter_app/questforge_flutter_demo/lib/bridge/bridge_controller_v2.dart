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

  static BridgeUiStateV2 empty() {
    final snap = DebugSnapshotV2(
      nodeId: '',
      isOver: false,
      cmdTypes: const <String>[],
      endActionLocked: false,
      pendingEndActionId: null,
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

/// 用來把後端 raw command map 包成 CommandV2
///（因為你目前的 CommandV2 是 abstract，沒有 fromJson）
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

    // ✅ sender：OverlayManagerV2 照舊用，但會真的打後端＋回寫 state
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

  final ValueNotifier<BridgeUiStateV2> stateVN = ValueNotifier<BridgeUiStateV2>(BridgeUiStateV2.empty());

  bool _started = false;

  // ------------------------------------------------------------
  // EndScreen lock/unlock
  // ------------------------------------------------------------
  final ValueNotifier<bool> endActionLockVN = ValueNotifier<bool>(false);
  final ValueNotifier<String?> pendingEndActionIdVN = ValueNotifier<String?>(null);

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

  bool get isUiBlocked {
    final b = stateVN.value.bundle;
    // ✅ 有 ask/quiz/end overlay 正在顯示時，阻擋 choose（避免重入）
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
    if (!endActionLockVN.value) endActionLockVN.value = true;

    _endActionTimeoutTimer?.cancel();
    _endActionTimeoutTimer = Timer(_endActionTimeoutDur, unlockEndAction);

    _refreshSnapshotOnly();
  }

  void unlockEndAction() {
    _endActionTimeoutTimer?.cancel();
    _endActionTimeoutTimer = null;

    if (pendingEndActionIdVN.value != null) pendingEndActionIdVN.value = null;
    if (endActionLockVN.value) endActionLockVN.value = false;

    _refreshSnapshotOnly();
  }

  // ------------------------------------------------------------
  // choose lock/unlock
  // ------------------------------------------------------------
  void clearAskOverlayLocal() {
    final old = stateVN.value;
    if (old.bundle.ask == null) return;
    stateVN.value = old.copyWith(bundle: old.bundle.copyWith(ask: null));
  }

  void clearEndOverlayLocal() {
    final old = stateVN.value;
    if (old.bundle.end == null) return;
    stateVN.value = old.copyWith(bundle: old.bundle.copyWith(end: null));
    _refreshSnapshotOnly();
  }

  void lockChoose(int index) {
    pendingChoiceIndexVN.value = index;
    if (!chooseLockVN.value) chooseLockVN.value = true;

    _chooseTimeoutTimer?.cancel();
    _chooseTimeoutTimer = Timer(_chooseTimeoutDur, unlockChoose);

    _refreshSnapshotOnly();
  }

  void unlockChoose() {
    _chooseTimeoutTimer?.cancel();
    _chooseTimeoutTimer = null;

    if (pendingChoiceIndexVN.value != null) pendingChoiceIndexVN.value = null;
    if (chooseLockVN.value) chooseLockVN.value = false;

    _refreshSnapshotOnly();
  }

  void _refreshSnapshotOnly() {
    final old = stateVN.value;
    final snap = old.snapshot.copyWith(
      endActionLocked: endActionLockVN.value,
      pendingEndActionId: pendingEndActionIdVN.value,
    );
    stateVN.value = old.copyWith(snapshot: snap);
  }

  // ------------------------------------------------------------
  // Public send APIs (Game UI / DebugPage 直接呼叫)
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

  /// EndScreen 點按（Overlay 也可能走 sender.sendUiAction）
  bool sendEndActionSpec(UiActionSpecV2 action) {
    if (endActionLockVN.value) return false;
    clearEndOverlayLocal(); // ✅ 先收起

    final id = (action.id ?? '').toString();
    debugPrint('[end_flow] tap: kind=${action.kind} id=${action.id} text=${action.text}');
    // ✅ kind 可能是 null（後端 options 只有 id/text），視為 end_flow
    final wireKind = (_kindToWire(action.kind).trim().isEmpty) ? 'end_flow' : _kindToWire(action.kind).trim();
    if (wireKind != 'end_flow') {
      debugPrint('[BridgeControllerV2] end action ignored: wireKind=$wireKind id=$id');
      return false;
    }

    final actionId = '$wireKind/$id';
    lockEndAction(actionId, pendingLabel: action.text);

    unawaited(() async {
      try {
        final r = await _api.endFlow(endAction: id);

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

  /// ✅ 給 BridgeDebugPage 用
  bool sendSetReasons({required List<String> reasonIds, String text = ''}) {
    if (chooseLockVN.value) return false;
    lockChoose(-2);
    sender.sendSetReasons(reasonIds: reasonIds, text: text);
    return true;
  }

  /// ✅ 給 BridgeDebugPage 用
  bool sendConfirmQuiz(List<Object?> answers, {bool skipped = false}) {
    if (chooseLockVN.value) return false;
    lockChoose(-3);
    sender.sendConfirmQuizAnswerList(answers, skipped: skipped);
    return true;
  }

  // ------------------------------------------------------------
  // sender callbacks (OverlayManagerV2 走 sender)
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
  // apply API bundle -> BridgeUiStateV2
  // ------------------------------------------------------------
  void _applyApiBundle({
    required Map<String, dynamic> bundle,
    required Map<String, dynamic> raw,
    bool? isOver,
  }) {
    final viewJson = bundle['view'];
    final NodeView? view = (viewJson is Map) ? NodeView.fromJson(Map<String, dynamic>.from(viewJson)) : null;

    // ✅ 重要：commands 就算 view == null 也要解析（EndScreen/Quiz/AskReason 都靠它）
    final commands = _commandsFromBundle(bundle);
    final parsedBundle = _router.parse(commands);

    // ✅ view 可能為 null（例如 show_end_screen command-only）
    //    這時 snapshot.nodeId 也不要空，從 command meta/node_id 推出來（避免 debug/overlay 依賴空值）
    final inferredNodeId = _inferNodeIdFromCommands(commands);

    final snap = DebugSnapshotV2(
      nodeId: view?.nodeId ?? inferredNodeId,
      isOver: isOver ?? false,
      cmdTypes: parsedBundle.types,
      endActionLocked: endActionLockVN.value,
      pendingEndActionId: pendingEndActionIdVN.value,
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
  }

  void _updateStateRawOnly(Map<String, dynamic> raw) {
    final old = stateVN.value;

    final snap = old.snapshot.copyWith(
      endActionLocked: endActionLockVN.value,
      pendingEndActionId: pendingEndActionIdVN.value,
      lastRawClip: _clipRaw(raw),
    );

    stateVN.value = old.copyWith(lastRaw: raw, snapshot: snap);
  }

  Map<String, dynamic> _clipRaw(Map<String, dynamic> raw) {
    final out = <String, dynamic>{};
    out['type'] = (raw['type'] ?? '').toString();
    if (raw.containsKey('session_id')) out['session_id'] = raw['session_id'];
    if (raw.containsKey('choice_index')) out['choice_index'] = raw['choice_index'];
    if (raw.containsKey('end_action')) out['end_action'] = raw['end_action'];

    final b = raw['bundle'];
    if (b is Map) {
      final bm = Map<String, dynamic>.from(b);

      final v = bm['view'];
      if (v is Map) {
        final vm = Map<String, dynamic>.from(v);
        out['view'] = <String, dynamic>{
          'nodeId': vm['nodeId'],
          'title': vm['title'],
          'choices_count': (vm['choices'] is List) ? (vm['choices'] as List).length : null,
        };
      }

      // ✅ 同時觀測兩種協定
      out['hasAsk'] = bm['ask'] != null;
      out['hasQuiz'] = bm['quiz'] != null;
      out['hasEnd'] = bm['end'] != null;

      final cmds = bm['commands'];
      if (cmds is List) out['commands_count'] = cmds.length;
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
  // Commands decode (兼容：bundle.commands / bundle.ask|quiz|end)
  // ------------------------------------------------------------
  List<CommandV2> _commandsFromBundle(Map<String, dynamic> bundle) {
    final out = <CommandV2>[];

    void addIfMap(dynamic v) {
      if (v is Map) out.add(WireCommandV2(Map<String, dynamic>.from(v)));
    }

    void addIfMapList(dynamic v) {
      if (v is! List) return;
      for (final it in v) {
        if (it is Map) out.add(WireCommandV2(Map<String, dynamic>.from(it)));
      }
    }

    // ✅ 新版（最常見）：後端直接回 commands: [{type:...}, ...]
    addIfMapList(bundle['commands']);

    // ✅ 舊版（你原本 router 用的）：ask/quiz/end 三段
    addIfMap(bundle['ask']);
    addIfMap(bundle['quiz']);
    addIfMap(bundle['end']);

    return out;
  }

  String _inferNodeIdFromCommands(List<CommandV2> commands) {
    for (final c in commands) {
      final raw = c.toJson();
      // show_end_screen: {node_id: "..."} or {nodeId: "..."}
      final nid = (raw['node_id'] ?? raw['nodeId'] ?? raw['meta']?['node_id'])?.toString().trim();
      if (nid != null && nid.isNotEmpty) return nid;
    }
    return '';
  }
}
