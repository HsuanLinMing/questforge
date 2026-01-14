// lib/dev/bridge/bridge_controller_v2.dart
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

class BridgeControllerV2 {
  BridgeControllerV2({
    required PythonBridge bridge,
    required String Function(Object? kind) kindToWire,
    CommandRouterV2 router = const CommandRouterV2(),
    Duration endActionTimeout = const Duration(seconds: 5),
  })  : _bridge = bridge,
        _router = router,
        _kindToWire = kindToWire,
        _endActionTimeoutDur = endActionTimeout,
        sender = BridgeSender(bridge) {
    stateVN.value = BridgeUiStateV2.empty();
  }

  final PythonBridge _bridge;
  final CommandRouterV2 _router;
  final String Function(Object? kind) _kindToWire;

  final BridgeSender sender;

  /// UI 監聽這個（view/commands/bundle/lastRaw/snapshot）
  final ValueNotifier<BridgeUiStateV2> stateVN = ValueNotifier<BridgeUiStateV2>(BridgeUiStateV2.empty());

  StreamSubscription<Map<String, dynamic>>? _sub;

  /// EndScreen 按鈕 lock 狀態（UI 只讀這兩個顯示「處理中」）
  final ValueNotifier<bool> endActionLockVN = ValueNotifier<bool>(false);
  final ValueNotifier<String?> pendingEndActionIdVN = ValueNotifier<String?>(null);

  /// 內建 timeout（避免永遠鎖死）
  final Duration _endActionTimeoutDur;
  Timer? _endActionTimeoutTimer;

  /// Day23-C：記住最後一次送出的 actionId，ack 只接受匹配的
  String? _lastSentEndActionId;

  bool get isStarted => _sub != null;
  bool get endActionLocked => endActionLockVN.value;

  bool get isUiBlocked {
    final b = stateVN.value.bundle;
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
  }

  void dispose() {
    stop();
    stateVN.dispose();
    endActionLockVN.dispose();
    pendingEndActionIdVN.dispose();
  }

  // ------------------------------------------------------------
  // EndScreen lock/unlock (controller 內建)
  // ------------------------------------------------------------

  void lockEndAction(String actionId, {String? pendingLabel}) {
    pendingEndActionIdVN.value = pendingLabel ?? actionId;
    if (!endActionLockVN.value) endActionLockVN.value = true;

    _endActionTimeoutTimer?.cancel();
    _endActionTimeoutTimer = Timer(_endActionTimeoutDur, () {
      // timeout：解鎖，但不 throw
      unlockEndAction();
    });

    _refreshSnapshotOnly();
  }

  void unlockEndAction() {
    _endActionTimeoutTimer?.cancel();
    _endActionTimeoutTimer = null;

    _lastSentEndActionId = null;

    if (pendingEndActionIdVN.value != null) pendingEndActionIdVN.value = null;
    if (endActionLockVN.value) endActionLockVN.value = false;

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

  /// ✅ 收斂：UI/Overlay 只要把 UiActionSpecV2 丟進來
  /// - 自動 kindToWire
  /// - 自動組 actionId
  /// - 自動 lock + timeout
  /// - 自動 send ui_action
  ///
  /// 回傳 true = 有送出；false = 被 lock/狀態擋下
  bool sendEndActionSpec(UiActionSpecV2 action) {
    // 1) 先擋 lock
    if (endActionLockVN.value) return false;

    // 2) 更嚴格：EndScreen 不在 bundle 時不送（避免 overlay race）
    if (stateVN.value.bundle.end == null) return false;

    final wireKind = _kindToWire(action.kind);
    final id = (action.id ?? '').toString();
    final actionId = '$wireKind/$id';

    final data = (action.data is Map) ? Map<String, dynamic>.from(action.data as Map) : null;

    // 記住最後送出的 actionId：ack 用來比對
    _lastSentEndActionId = actionId;

    // pending label：用 action.text 最直覺
    lockEndAction(actionId, pendingLabel: action.text);

    sender.sendUiAction(kind: wireKind, id: id, data: data);
    return true;
  }

  // ------------------------------------------------------------
  // Day23-C: ui_action_ack (non-step_result) — ONLY for UI hint/debug
  // ------------------------------------------------------------

  /// 回傳 true = 這個 raw 是 ack（已處理/吃掉，不走 step_result parse）
bool _tryHandleUiActionAck(Map<String, dynamic> raw) {
  final type = (raw['type'] ?? '').toString();
  if (type != 'ui_action_ack') return false;

  final payload = raw['payload'];
  if (payload is! Map) {
    // 仍然要讓 snapshot 記錄「收過 ack，但格式怪」
    final old = stateVN.value;
    stateVN.value = old.copyWith(
      snapshot: old.snapshot.copyWith(
        lastAck: <String, dynamic>{'malformed': true},
      ),
    );
    return true;
  }

  final p = Map<String, dynamic>.from(payload);
  final kind = (p['kind'] ?? '').toString();
  final id = (p['id'] ?? '').toString();
  final status = (p['status'] ?? '').toString();

  // ✅ ack 只做 UI 呈現：更新 pending label（不要解鎖！）
  if (endActionLockVN.value) {
    final base = (kind.isEmpty || id.isEmpty) ? '已收到' : '已收到：$kind/$id';
    final label = status.isEmpty ? base : '$base（$status）';
    pendingEndActionIdVN.value = label;
  }

  // ✅ Day23-E：把 ack 收進 DebugSnapshot（不依賴 lastRawClip，避免被 _clipRaw 截掉）
  final old = stateVN.value;
  stateVN.value = old.copyWith(
    snapshot: old.snapshot.copyWith(
      endActionLocked: endActionLockVN.value,
      pendingEndActionId: pendingEndActionIdVN.value,
      lastAck: <String, dynamic>{
        if (kind.isNotEmpty) 'kind': kind,
        if (id.isNotEmpty) 'id': id,
        if (status.isNotEmpty) 'status': status,
      },
    ),
  );

  return true;
}

  void _onRaw(Map<String, dynamic> raw) {
    // ✅ 先吃掉 ack（不影響 step_result 流；也不要在 ack 解鎖）
    if (_tryHandleUiActionAck(raw)) {
      _updateStateRawOnly(raw); // 讓 debug page 仍顯示 lastRaw/snapshot
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

    // ✅ 有新的 step_result 代表引擎已回應：解鎖 end action
    unlockEndAction();

    final view = step.view;
    final commands = step.commands;
    final bundle = _router.parse(commands);

    final snap = DebugSnapshotV2(
      nodeId: '',
      isOver: false,
      cmdTypes: const <String>[],
      endActionLocked: false,
      pendingEndActionId: null,
      lastRawClip: null,
     lastAck: stateVN.value.snapshot.lastAck,
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
      // lastAck: old.snapshot.lastAck  // copyWith 預設會保留，不用特別寫
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
          'choices_count': (viewMap['choices'] is List) ? (viewMap['choices'] as List).length : null,
        };
      }

      final cmds = payloadMap['commands'];
      if (cmds is List) p['commands_count'] = cmds.length;

      // Day23-C: ack snapshot fields (match your python sample)
      if (payloadMap.containsKey('kind')) p['kind'] = payloadMap['kind'];
      if (payloadMap.containsKey('id')) p['id'] = payloadMap['id'];
      if (payloadMap.containsKey('status')) p['status'] = payloadMap['status'];

      out['payload'] = p;
    }

    return out;
  }
}
