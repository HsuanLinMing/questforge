// lib/src/v2/accuse_evaluator_v2.dart
// Option B: Accuse evaluator contract (Flutter <-> FastAPI)

/// Evaluator decision.
/// - [accuse]: evaluator believes we can pick a suspect choice
/// - [deferToTeacher]: evaluator believes we should defer to teacher (no re-say)
enum AccuseDecisionV2 {
  accuse,
  deferToTeacher,
}

AccuseDecisionV2 accuseDecisionV2FromWire(String? s) {
  final v = (s ?? '').trim();
  if (v == 'accuse') return AccuseDecisionV2.accuse;
  if (v == 'defer_to_teacher') return AccuseDecisionV2.deferToTeacher;
  // fallback: be safe
  return AccuseDecisionV2.deferToTeacher;
}

String accuseDecisionV2ToWire(AccuseDecisionV2 d) {
  switch (d) {
    case AccuseDecisionV2.accuse:
      return 'accuse';
    case AccuseDecisionV2.deferToTeacher:
      return 'defer_to_teacher';
  }
}

class AccuseEvaluateRequestV2 {
  AccuseEvaluateRequestV2({
    required this.sessionId,
    required this.recognizedText,
    this.nodeId,
  });

  final String sessionId;
  final String recognizedText;
  final String? nodeId;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'session_id': sessionId,
        'recognized_text': recognizedText,
        if (nodeId != null) 'node_id': nodeId,
      };
}

class AccuseEvaluateResponseV2 {
  AccuseEvaluateResponseV2({
    required this.decision,
    required this.score,
    required this.threshold,
    required this.fifiReply,
    this.matchedChoiceIndex,
    this.matchedChoiceText,
    this.deferChoiceIndex,
    this.autoSubmit,
    this.debug,
  });

  final AccuseDecisionV2 decision;
  final double score;
  final double threshold;

  /// What Fifi should say to "catch" the child.
  final String fifiReply;

  /// Choice index to choose when decision=accuse.
  final int? matchedChoiceIndex;
  final String? matchedChoiceText;

  /// Choice index for "defer to teacher" if exists.
  final int? deferChoiceIndex;

  /// Whether UI should auto-submit immediately.
  final bool? autoSubmit;

  final Map<String, dynamic>? debug;

  factory AccuseEvaluateResponseV2.fromJson(Map<String, dynamic> json) {
    double _asDouble(Object? v, [double fallback = 0]) {
      if (v is num) return v.toDouble();
      return double.tryParse((v ?? '').toString()) ?? fallback;
    }

    int? _asInt(Object? v) {
      if (v == null) return null;
      if (v is int) return v;
      if (v is num) return v.toInt();
      return int.tryParse(v.toString());
    }

    Map<String, dynamic>? _asMap(Object? v) {
      if (v is Map<String, dynamic>) return v;
      if (v is Map) return v.cast<String, dynamic>();
      return null;
    }

    return AccuseEvaluateResponseV2(
      decision: accuseDecisionV2FromWire(json['decision']?.toString()),
      score: _asDouble(json['score'], 0),
      threshold: _asDouble(json['threshold'], 0.6),
      fifiReply: (json['fifi_reply'] ?? '').toString(),
      matchedChoiceIndex: _asInt(json['matched_choice_index']),
      matchedChoiceText: json['matched_choice_text']?.toString(),
      deferChoiceIndex: _asInt(json['defer_choice_index']),
      autoSubmit: json['auto_submit'] as bool?,
      debug: _asMap(json['debug']),
    );
  }
}
