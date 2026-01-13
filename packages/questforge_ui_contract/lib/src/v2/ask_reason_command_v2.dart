import '../utils.dart';
import 'command_base_v2.dart';

class AskReasonCommandV2 extends CommandV2 {
  AskReasonCommandV2({
    required this.mode,
    required this.options,
    required this.title,
    required this.hint,
    required this.maxLen,
  });

  @override
  String get type => 'ask_reason';

  final String mode; // "choice" | "text"
  final List<ReasonOptionV2> options;
  final String title;
  final String hint;
  final int maxLen;

  static AskReasonCommandV2 fromJson(Map<String, dynamic> json) {
    return AskReasonCommandV2(
      mode: asString(pick(json, 'mode'), 'choice'),
      options: asListOf<ReasonOptionV2>(
        pick(json, 'options'),
        (x) => ReasonOptionV2.fromJson(normalizeJsonMap(x)),
      ),
      title: asString(pick(json, 'title')),
      hint: asString(pick(json, 'hint')),
      maxLen: asInt(pick(json, 'max_len'), 80),
    );
  }

  @override
  Map<String, dynamic> toJson() => {
        'type': type,
        'mode': mode,
        'options': options.map((e) => e.toJson()).toList(growable: false),
        'title': title,
        'hint': hint,
        'max_len': maxLen,
      };
}

class ReasonOptionV2 implements JsonCodable {
  const ReasonOptionV2({
    this.id = '',
    this.text = '',
    this.expectedEvidence = const <String>[],
  });

  final String id;
  final String text;
  final List<String> expectedEvidence;

  static ReasonOptionV2 fromJson(Map<String, dynamic> json) {
    return ReasonOptionV2(
      id: asString(pick(json, 'id')),
      text: asString(pick(json, 'text')),
      expectedEvidence:
          asListOf<String>(pick(json, 'expected_evidence'), (x) => asString(x)),
    );
  }

  @override
  Map<String, dynamic> toJson() => {
        'id': id,
        'text': text,
        'expected_evidence': List<String>.from(expectedEvidence),
      };
}
