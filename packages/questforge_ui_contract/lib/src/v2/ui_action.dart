// lib/src/v2/ui_action.dart
import 'actions.dart';

class UiActionV2 {
  /// Always: "ui_action"
  final String type;

  /// e.g. end_flow
  final UiActionKindV2 kind;

  /// action id, e.g. "go_epilogue"
  final String id;

  /// optional data
  final Map<String, dynamic>? data;

  const UiActionV2({
    this.type = 'ui_action',
    required this.kind,
    required this.id,
    this.data,
  });

  factory UiActionV2.fromJson(Map<String, dynamic> json) {
    final payload = (json['payload'] as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};
    return UiActionV2(
      kind: UiActionKindV2.fromString((payload['kind'] ?? '').toString()),
      id: (payload['id'] ?? '').toString(),
      data: (payload['data'] as Map?)?.cast<String, dynamic>(),
    );
  }

  Map<String, dynamic> toJson() => {
        'type': type,
        'payload': {
          'kind': kind.value,
          'id': id,
          if (data != null) 'data': data,
        },
      };
}
