import 'utils.dart';

class NodeView implements JsonCodable {
  const NodeView({
    this.nodeId = '',
    this.title = '',
    this.narration = '',
    this.next = '',
    this.meta = const <String, dynamic>{},
    this.choices = const <ChoiceView>[],
  });

  final String nodeId;
  final String title;
  final String narration;
  final String next;
  final Map<String, dynamic> meta;
  final List<ChoiceView> choices;

  static NodeView fromJson(Object? json) {
    final m = normalizeJsonMap(json);
    return NodeView(
      nodeId: asString(pick(m, 'node_id')),
      title: asString(pick(m, 'title')),
      narration: asString(pick(m, 'narration')),
      next: asString(pick(m, 'next')),
      meta: (pick(m, 'meta') as Map?)?.cast<String, dynamic>() ??
          <String, dynamic>{},
      choices: asListOf<ChoiceView>(pick(m, 'choices'), ChoiceView.fromJson),
    );
  }

  @override
  JsonMap toJson() => <String, dynamic>{
        'node_id': nodeId,
        'title': title,
        'narration': narration,
        'next': next,
        'meta': meta,
        'choices': choices.map((e) => e.toJson()).toList(growable: false),
      };
}

class ChoiceView implements JsonCodable {
  const ChoiceView({
    this.index = 0,
    this.text = '',
    this.enabled = true,
    this.reason,
    this.tag = '',
  });

  final int index;
  final String text;
  final bool enabled;
  final String? reason; // "after" text (optional)
  final String tag; // e.g. edit_reasons / back_to_investigate (if UI uses)

  static ChoiceView fromJson(Object? json) {
    final m = normalizeJsonMap(json);
    final r = pick(m, 'reason');
    return ChoiceView(
      index: asInt(pick(m, 'index')),
      text: asString(pick(m, 'text')),
      enabled: asBool(pick(m, 'enabled'), true),
      reason: (r == null) ? null : asString(r),
      tag: asString(pick(m, 'tag')),
    );
  }

  @override
  JsonMap toJson() => <String, dynamic>{
        'index': index,
        'text': text,
        'enabled': enabled,
        'reason': reason,
        'tag': tag,
      };
}
