// lib/src/v2/actions.dart
enum UiActionKindV2 {
  endFlow,
  unknown;

  static UiActionKindV2 fromString(String v) {
    switch (v) {
      case 'end_flow':
        return UiActionKindV2.endFlow;
      default:
        return UiActionKindV2.unknown;
    }
  }

  String get value {
    switch (this) {
      case UiActionKindV2.endFlow:
        return 'end_flow';
      case UiActionKindV2.unknown:
        return 'unknown';
    }
  }
}

class UiActionSpecV2 {
  /// stable id, e.g. "go_epilogue", "restart_case"
  final String id;

  /// display text on UI
  final String text;

  /// e.g. end_flow
  final UiActionKindV2 kind;

  /// optional extra
  final Map<String, dynamic>? data;

  const UiActionSpecV2({
    required this.id,
    required this.text,
    required this.kind,
    this.data,
  });

  factory UiActionSpecV2.fromJson(Map<String, dynamic> json) {
    return UiActionSpecV2(
      id: (json['id'] ?? '').toString(),
      text: (json['text'] ?? '').toString(),
      kind: UiActionKindV2.fromString((json['kind'] ?? '').toString()),
      data: (json['data'] as Map?)?.cast<String, dynamic>(),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'text': text,
        'kind': kind.value,
        if (data != null) 'data': data,
      };
}
