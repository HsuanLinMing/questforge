// lib/dev/bridge/debug_snapshot.dart

class DebugSnapshotV2 {
  final String nodeId;
  final bool isOver;
  final List<String> cmdTypes;

  final bool endActionLocked;
  final String? pendingEndActionId;

  /// 最後一次 raw 的裁切資訊（debug 用）
  final Map<String, dynamic>? lastRawClip;

  /// ✅ Day23-E：最後一次 ui_action_ack（debug 用）
  /// e.g. {"kind":"end_flow","id":"quit","status":"received"}
  final Map<String, dynamic>? lastAck;

  const DebugSnapshotV2({
    required this.nodeId,
    required this.isOver,
    required this.cmdTypes,
    required this.endActionLocked,
    required this.pendingEndActionId,
    required this.lastRawClip,
    required this.lastAck,
  });

  DebugSnapshotV2 copyWith({
    String? nodeId,
    bool? isOver,
    List<String>? cmdTypes,
    bool? endActionLocked,
    String? pendingEndActionId,
    Map<String, dynamic>? lastRawClip,
    Map<String, dynamic>? lastAck,
  }) {
    return DebugSnapshotV2(
      nodeId: nodeId ?? this.nodeId,
      isOver: isOver ?? this.isOver,
      cmdTypes: cmdTypes ?? this.cmdTypes,
      endActionLocked: endActionLocked ?? this.endActionLocked,
      pendingEndActionId: pendingEndActionId ?? this.pendingEndActionId,
      lastRawClip: lastRawClip ?? this.lastRawClip,
      lastAck: lastAck ?? this.lastAck,
    );
  }

  Map<String, dynamic> toJson() => <String, dynamic>{
        'node_id': nodeId,
        'is_over': isOver,
        'cmd_types': cmdTypes,
        'end_lock': endActionLocked,
        'pending_end_action': pendingEndActionId,
        'last_ack': lastAck,
        'last_raw_clip': lastRawClip,
      };
}
