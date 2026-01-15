import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:questforge_flutter_demo/dev/python_bridge.dart';
import 'package:questforge_ui_contract/questforge_contract.dart';

import 'bridge_sender.dart';
import 'command_router.dart';
import 'debug_snapshot.dart';

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
      lastAck:null
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

class BridgeControllerV2 {
  BridgeControllerV2({
    required PythonBridge bridge,
    required String Function(Object? kind) kindToWire,
    CommandRouterV2 router = const CommandRouterV2(),
    Duration endActionTimeout = const Duration(seconds: 5),
    Duration chooseActionTimeout = const Duration(seconds: 5),
  })  : _bridge = bridge,
        _router = router,
        _kindToWire = kindToWire,
        _endActionTimeoutDur = endActionTimeout,
        _chooseTimeoutDur = chooseActionTimeout,
        sender = BridgeSender(bridge) {
    stateVN.value = BridgeUiStateV2.empty();
  }

  final PythonBridge _bridge;
  final CommandRouterV2 _router;
  final String Function(Object? kind) _kindToWire;

  final BridgeSender sender;

  final ValueNotifier<BridgeUiStateV2> stateVN =
      ValueNotifier<BridgeUiStateV2>(BridgeUiStateV2.empty());

  StreamSubscription<Map<String, dynamic>>? _sub;

  // ------------------------------------------------------------
  // EndScreen lock/unlock
  // ------------------------------------------------------------
  final ValueNotifier<bool> endActionLockVN = ValueNotifier<bool>(false);
  final ValueNotifier<String?> pendingEndActionIdVN =
      ValueNotifier<String?>(null);

  final Duration _endActionTimeoutDur;
  Timer? _endActionTimeoutTimer;

  // ------------------------------------------------------------
  // ✅ Day24-C: choose lock/unlock
  // - 點選選項後鎖住（避免連點）
  // - 顯示 pendingChoiceIndex
  // - 收到 step_result 才解鎖（或 timeout）
  // ------------------------------------------------------------
  final ValueNotifier<bool> chooseLockVN = ValueNotifier<bool>(false);
  final ValueNotifier<int?> pendingChoiceIndexVN = ValueNotifier<int?>(null);

  final Duration _chooseTimeoutDur;
  Timer? _chooseTimeoutTimer;

  bool get isStarted => _sub != null;
  bool get endActionLocked => endActionLockVN.value;
  bool get chooseLocked => chooseLockVN.value;

  bool get isUiBlocked {
    final b = stateVN.value.bundle;
    // overlays 開著時，一樣視為 blocked
    return b.end != null || b.ask != null || b.quiz != null;
  }

  void start() {
    _sub ??= _bridge.outputs.listen(_onRaw);
  }

  void stop() {
    _sub?.cancel();
    _sub = null;

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

  // ------------------------------------------------------------
  // EndScreen lock/unlock
  // ------------------------------------------------------------

  void lockEndAction(String actionId, {String? pendingLabel}) {
    pendingEndActionIdVN.value = pendingLabel ?? actionId;
    if (!endActionLockVN.value) endActionLockVN.value = true;

    _endActionTimeoutTimer?.cancel();
    _endActionTimeoutTimer = Timer(_endActionTimeoutDur, () {
      unlockEndAction();
    });

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
  // ✅ Day24-C: choose lock/unlock
  // ------------------------------------------------------------

  void lockChoose(int index) {
    pendingChoiceIndexVN.value = index;
    if (!chooseLockVN.value) chooseLockVN.value = true;

    _chooseTimeoutTimer?.cancel();
    _chooseTimeoutTimer = Timer(_chooseTimeoutDur, () {
      unlockChoose();
    });

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
  // Public send APIs (for Game UI)
  // ------------------------------------------------------------

  bool sendEndActionSpec(UiActionSpecV2 action) {
    if (endActionLockVN.value) return false;

    final wireKind = _kindToWire(action.kind);
    final id = (action.id ?? '').toString();
    final actionId = '$wireKind/$id';

    final data = (action.data is Map)
        ? Map<String, dynamic>.from(action.data as Map)
        : null;

    lockEndAction(actionId, pendingLabel: action.text);
    sender.sendUiAction(kind: wireKind, id: id, data: data);
    return true;
  }

  /// ✅ Day24-C：給正式 UI 用的 choose（帶 lock）
  bool sendChoose(int index) {
    if (chooseLockVN.value) return false;
    if (isUiBlocked) return false;

    lockChoose(index);
    sender.sendChoose(index);
    return true;
  }

  /// ✅ Day24-C：給正式 UI 用的 replay（也走 choose lock，避免連點）
  bool sendReplay() {
    if (chooseLockVN.value) return false;
    if (isUiBlocked) return false;

    // 用 -1 表示 replay（只拿來顯示送出中狀態）
    lockChoose(-1);
    sender.sendReplay();
    return true;
  }

  // ------------------------------------------------------------
  // Day23-C: ui_action_ack — ONLY for UI hint/debug
  // ------------------------------------------------------------
  bool _tryHandleUiActionAck(Map<String, dynamic> raw) {
    final type = (raw['type'] ?? '').toString();
    if (type != 'ui_action_ack') return false;

    final payload = raw['payload'];
    if (payload is! Map) return true;

    final p = Map<String, dynamic>.from(payload);
    final kind = (p['kind'] ?? '').toString();
    final id = (p['id'] ?? '').toString();
    final status = (p['status'] ?? '').toString();

    if (endActionLockVN.value) {
      final base =
          (kind.isEmpty || id.isEmpty) ? '已收到' : '已收到：$kind/$id';
      final label = status.isEmpty ? base : '$base（$status）';
      pendingEndActionIdVN.value = label;
      _refreshSnapshotOnly();
    }

    return true;
  }

  void _onRaw(Map<String, dynamic> raw) {
    if (_tryHandleUiActionAck(raw)) {
      _updateStateRawOnly(raw);
      return;
    }

    StepResultV2? step;
    try {
      step = StepResultParserV2.parse(raw);
    } catch (_) {
      _updateStateRawOnly(raw);
      return;
    }

    if (step == null) {
      _updateStateRawOnly(raw);
      return;
    }

    // ✅ 收到 step_result：代表引擎已回應，解除所有 UI 操作鎖
    unlockEndAction();
    unlockChoose();

    final view = step.view;
    final commands = step.commands;
    final bundle = _router.parse(commands);
    final old = stateVN.value;
    final snap = DebugSnapshotV2(
      nodeId: view?.nodeId ?? '',
      isOver: step.isOver,
      cmdTypes: bundle.types,
      endActionLocked: endActionLockVN.value,
      pendingEndActionId: pendingEndActionIdVN.value,
      lastRawClip: _clipRaw(raw),
      lastAck: old.snapshot.lastAck,
    );

    stateVN.value = stateVN.value.copyWith(
      view: view,
      commands: commands,
      bundle: bundle,
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

    stateVN.value = old.copyWith(
      lastRaw: raw,
      snapshot: snap,
    );
  }

  Map<String, dynamic> _clipRaw(Map<String, dynamic> raw) {
    final out = <String, dynamic>{};

    if (raw.containsKey('contract_version')) {
      out['contract_version'] = raw['contract_version'];
    }
    if (raw.containsKey('type')) out['type'] = raw['type'];

    final payload = raw['payload'];
    if (payload is Map) {
      final payloadMap = Map<String, dynamic>.from(payload as Map);
      final p = <String, dynamic>{};

      final v = payloadMap['view'];
      if (v is Map) {
        final viewMap = Map<String, dynamic>.from(v as Map);
        p['view'] = <String, dynamic>{
          'node_id': viewMap['node_id'],
          'title': viewMap['title'],
          'choices_count': (viewMap['choices'] is List)
              ? (viewMap['choices'] as List).length
              : null,
        };
      }

      final cmds = payloadMap['commands'];
      if (cmds is List) p['commands_count'] = cmds.length;

      if (payloadMap.containsKey('kind')) p['kind'] = payloadMap['kind'];
      if (payloadMap.containsKey('id')) p['id'] = payloadMap['id'];
      if (payloadMap.containsKey('status')) p['status'] = payloadMap['status'];

      out['payload'] = p;
    }

    return out;
  }
}
