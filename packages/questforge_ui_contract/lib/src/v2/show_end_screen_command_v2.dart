// lib/src/v2/show_end_screen_command_v2.dart
import 'package:questforge_ui_contract/src/v2/command_base_v2.dart';

import 'actions.dart';
import 'reasoning_summary_v2.dart';

class EndContentV2 {
  final String title;
  final String narration;
  final List<String> lessons;
  final Map<String, dynamic>? meta;

  const EndContentV2({
    required this.title,
    required this.narration,
    required this.lessons,
    this.meta,
  });

  factory EndContentV2.fromJson(Map<String, dynamic> json) {
    return EndContentV2(
      title: (json['title'] ?? '').toString(),
      narration: (json['narration'] ?? '').toString(),
      lessons: (json['lessons'] as List?)?.map((e) => e.toString()).toList() ?? const <String>[],
      meta: (json['meta'] as Map?)?.cast<String, dynamic>(),
    );
  }

  Map<String, dynamic> toJson() => {
        'title': title,
        'narration': narration,
        'lessons': lessons,
        if (meta != null) 'meta': meta,
      };
}

class ShowEndScreenCommandV2 implements CommandV2 {
  @override
  final String type; // "show_end_screen"

  final EndContentV2 end;
  final ReasoningSummaryV2? summary;
  final List<UiActionSpecV2> actions;

  final String? nextHint;
  final Map<String, dynamic>? debug;
  final Map<String, dynamic>? analytics;

  const ShowEndScreenCommandV2({
    this.type = 'show_end_screen',
    required this.end,
    required this.summary,
    required this.actions,
    this.nextHint,
    this.debug,
    this.analytics,
  });

  factory ShowEndScreenCommandV2.fromJson(Map<String, dynamic> json) {
    return ShowEndScreenCommandV2(
      type: (json['type'] ?? 'show_end_screen').toString(),
      end: EndContentV2.fromJson((json['end'] as Map?)?.cast<String, dynamic>() ?? const {}),
      summary: (json['summary'] is Map)
          ? ReasoningSummaryV2.fromJson(((json['summary'] as Map)['reasoning'] as Map?)?.cast<String, dynamic>() ?? const {})
          : null,
      actions: (json['actions'] as List?)?.map((e) => UiActionSpecV2.fromJson((e as Map).cast<String, dynamic>())).toList() ?? const [],
      nextHint: json['next_hint']?.toString(),
      debug: (json['debug'] as Map?)?.cast<String, dynamic>(),
      analytics: (json['analytics'] as Map?)?.cast<String, dynamic>(),
    );
  }
  @override
  Map<String, dynamic> toJson() => {
        'type': type,
        'end': end.toJson(),
        'summary': summary == null ? null : {'reasoning': summary!.toJson()},
        'actions': actions.map((e) => e.toJson()).toList(),
        if (nextHint != null) 'next_hint': nextHint,
        if (debug != null) 'debug': debug,
        if (analytics != null) 'analytics': analytics,
      };
}

extension EndContentV2MetaExt on EndContentV2 {
  String get nodeId => (meta?['node_id'] ?? meta?['nodeId'] ?? '').toString();
  String get tag => (meta?['tag'] ?? '').toString();
}