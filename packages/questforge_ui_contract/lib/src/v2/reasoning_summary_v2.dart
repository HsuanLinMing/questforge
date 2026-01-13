// lib/src/v2/reasoning_summary_v2.dart

class ReasoningReasonV2 {
  /// e.g. "observations" | "free_text" | "teacher"
  final String mode;

  /// observation ids user selected
  final List<String> selectedObservationIds;

  /// optional free text
  final String text;

  const ReasoningReasonV2({
    required this.mode,
    required this.selectedObservationIds,
    required this.text,
  });

  factory ReasoningReasonV2.fromJson(Map<String, dynamic> json) {
    return ReasoningReasonV2(
      mode: (json['mode'] ?? '').toString(),
      selectedObservationIds: (json['selected_observation_ids'] as List?)
              ?.map((e) => e.toString())
              .toList() ??
          const <String>[],
      text: (json['text'] ?? '').toString(),
    );
  }

  Map<String, dynamic> toJson() => {
        'mode': mode,
        'selected_observation_ids': selectedObservationIds,
        'text': text,
      };
}

class ReasoningEvaluationV2 {
  /// e.g. "great" | "ok" | "needs_more" (engine-defined)
  final String level;

  /// engine score 0~100 (or 0~1), keep flexible
  final num score;

  /// engine threshold
  final num threshold;

  /// message engine wants to show on UI (kid-friendly)
  final String engineMessage;

  const ReasoningEvaluationV2({
    required this.level,
    required this.score,
    required this.threshold,
    required this.engineMessage,
  });

  factory ReasoningEvaluationV2.fromJson(Map<String, dynamic> json) {
    return ReasoningEvaluationV2(
      level: (json['level'] ?? '').toString(),
      score: (json['score'] is num) ? (json['score'] as num) : num.tryParse((json['score'] ?? '0').toString()) ?? 0,
      threshold: (json['threshold'] is num) ? (json['threshold'] as num) : num.tryParse((json['threshold'] ?? '0').toString()) ?? 0,
      engineMessage: (json['engine_message'] ?? '').toString(),
    );
  }

  Map<String, dynamic> toJson() => {
        'level': level,
        'score': score,
        'threshold': threshold,
        'engine_message': engineMessage,
      };
}

class EvidenceItemV2 {
  final String id; // stable id
  final String text;

  const EvidenceItemV2({required this.id, required this.text});

  factory EvidenceItemV2.fromJson(Map<String, dynamic> json) {
    return EvidenceItemV2(
      id: (json['id'] ?? '').toString(),
      text: (json['text'] ?? '').toString(),
    );
  }

  Map<String, dynamic> toJson() => {'id': id, 'text': text};
}

class ReasoningSummaryV2 {
  final String caseTitle;
  final int turn;

  /// accused / suspect (你想用 accused 我就固定 accused；UI 可顯示「你選的是…」)
  final String accused;

  final ReasoningReasonV2 reason;

  /// small preview for UI
  final List<String> cluesPreview;

  final ReasoningEvaluationV2 evaluation;

  final List<EvidenceItemV2> matchedEvidence;
  final List<EvidenceItemV2> missingKeyEvidence;

  const ReasoningSummaryV2({
    required this.caseTitle,
    required this.turn,
    required this.accused,
    required this.reason,
    required this.cluesPreview,
    required this.evaluation,
    required this.matchedEvidence,
    required this.missingKeyEvidence,
  });

  factory ReasoningSummaryV2.fromJson(Map<String, dynamic> json) {
    return ReasoningSummaryV2(
      caseTitle: (json['case_title'] ?? '').toString(),
      turn: (json['turn'] is int) ? (json['turn'] as int) : int.tryParse((json['turn'] ?? '0').toString()) ?? 0,
      accused: (json['accused'] ?? '').toString(),
      reason: ReasoningReasonV2.fromJson((json['reason'] as Map?)?.cast<String, dynamic>() ?? const <String, dynamic>{}),
      cluesPreview: (json['clues_preview'] as List?)?.map((e) => e.toString()).toList() ?? const <String>[],
      evaluation: ReasoningEvaluationV2.fromJson((json['evaluation'] as Map?)?.cast<String, dynamic>() ?? const <String, dynamic>{}),
      matchedEvidence: (json['matched_evidence'] as List?)
              ?.map((e) => EvidenceItemV2.fromJson((e as Map).cast<String, dynamic>()))
              .toList() ??
          const <EvidenceItemV2>[],
      missingKeyEvidence: (json['missing_key_evidence'] as List?)
              ?.map((e) => EvidenceItemV2.fromJson((e as Map).cast<String, dynamic>()))
              .toList() ??
          const <EvidenceItemV2>[],
    );
  }

  Map<String, dynamic> toJson() => {
        'case_title': caseTitle,
        'turn': turn,
        'accused': accused,
        'reason': reason.toJson(),
        'clues_preview': cluesPreview,
        'evaluation': evaluation.toJson(),
        'matched_evidence': matchedEvidence.map((e) => e.toJson()).toList(),
        'missing_key_evidence': missingKeyEvidence.map((e) => e.toJson()).toList(),
      };
}
