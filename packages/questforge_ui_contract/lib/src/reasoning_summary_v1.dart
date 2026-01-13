import 'utils.dart';

/// Keep in sync with Python:
/// CONTRACT_VERSION = "reasoning_contract_v1"
const String reasoningContractVersion = 'reasoning_contract_v1';

/// Reasoning contract v1 (stable schema for Flutter/UI).
///
/// Python ensure_reasoning_contract_v1(meta) will normalize keys.
/// This Dart model is tolerant to missing fields.
class ReasoningSummaryV1 implements JsonCodable {
  const ReasoningSummaryV1({
    this.version = reasoningContractVersion,
    this.caseTitle = '',
    this.nodeId = '',
    this.tag = 'ending_check',
    this.turn = 0,
    this.accused = '',
    this.reasonMode = 'choice',
    this.reasonIds = const <String>[],
    this.selectedObservations = const <String>[],
    this.reasonText = '',
    this.reasonSummary = '',
    this.cluesPreview = const <String>[],
    this.level = 'weak',
    this.score = 0,
    this.threshold = 0,
    this.engineMessage = '',
    this.matchedEvidence = const <String>[],
    this.missingKeyEvidence = const <String>[],
  });

  final String version;

  // context
  final String caseTitle;
  final String nodeId;
  final String tag; // ending_result|ending_wrong|epilogue|ending_check
  final int turn;

  // accuse / reason
  final String accused;
  final String reasonMode; // choice|text|voice
  final List<String> reasonIds;
  final List<String> selectedObservations;
  final String reasonText;
  final String reasonSummary;

  // evidence
  final List<String> cluesPreview;

  // scoring
  final String level; // weak|ok|good
  final int score;
  final int threshold;
  final String engineMessage;

  final List<String> matchedEvidence;
  final List<String> missingKeyEvidence;

  static ReasoningSummaryV1 fromJson(Object? json) {
    final m = normalizeJsonMap(json);
    return ReasoningSummaryV1(
      version: asString(pick(m, 'version'), reasoningContractVersion),
      caseTitle: asString(pick(m, 'case_title')),
      nodeId: asString(pick(m, 'node_id')),
      tag: asString(pick(m, 'tag'), 'ending_check'),
      turn: asInt(pick(m, 'turn')),
      accused: asString(pick(m, 'accused')),
      reasonMode: asString(pick(m, 'reason_mode'), 'choice'),
      reasonIds: asListOf<String>(pick(m, 'reason_ids'), (x) => asString(x)),
      selectedObservations: asListOf<String>(
        pick(m, 'selected_observations'),
        (x) => asString(x),
      ),
      reasonText: asString(pick(m, 'reason_text')),
      reasonSummary: asString(pick(m, 'reason_summary')),
      cluesPreview: asListOf<String>(pick(m, 'clues_preview'), (x) => asString(x)),
      level: asString(pick(m, 'level'), 'weak'),
      score: asInt(pick(m, 'score')),
      threshold: asInt(pick(m, 'threshold')),
      engineMessage: asString(pick(m, 'engine_message')),
      matchedEvidence:
          asListOf<String>(pick(m, 'matched_evidence'), (x) => asString(x)),
      missingKeyEvidence:
          asListOf<String>(pick(m, 'missing_key_evidence'), (x) => asString(x)),
    );
  }

  @override
  JsonMap toJson() => <String, dynamic>{
        'version': version,
        'case_title': caseTitle,
        'node_id': nodeId,
        'tag': tag,
        'turn': turn,
        'accused': accused,
        'reason_mode': reasonMode,
        'reason_ids': List<String>.from(reasonIds),
        'selected_observations': List<String>.from(selectedObservations),
        'reason_text': reasonText,
        'reason_summary': reasonSummary,
        'clues_preview': List<String>.from(cluesPreview),
        'level': level,
        'score': score,
        'threshold': threshold,
        'engine_message': engineMessage,
        'matched_evidence': List<String>.from(matchedEvidence),
        'missing_key_evidence': List<String>.from(missingKeyEvidence),
      };
}
