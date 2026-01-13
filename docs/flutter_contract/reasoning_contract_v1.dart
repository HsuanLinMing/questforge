// lib/core/contracts/reasoning_contract_v1.dart
import 'dart:convert';

/// contract version (engine)
const kReasoningContractV1 = 'reasoning_contract_v1';

enum ReasoningLevel { weak, ok, good, unknown }
enum EndTag { endingResult, endingWrong, epilogue, endingCheck, unknown }

ReasoningLevel reasoningLevelFrom(String? s) {
  switch ((s ?? '').trim()) {
    case 'weak':
      return ReasoningLevel.weak;
    case 'ok':
      return ReasoningLevel.ok;
    case 'good':
      return ReasoningLevel.good;
    default:
      return ReasoningLevel.unknown;
  }
}

EndTag endTagFrom(String? s) {
  switch ((s ?? '').trim()) {
    case 'ending_result':
      return EndTag.endingResult;
    case 'ending_wrong':
      return EndTag.endingWrong;
    case 'epilogue':
      return EndTag.epilogue;
    case 'ending_check':
      return EndTag.endingCheck;
    default:
      return EndTag.unknown;
  }
}

int _asInt(dynamic v, {int fallback = 0}) {
  if (v is int) return v;
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v.trim()) ?? fallback;
  return fallback;
}

String _asString(dynamic v, {String fallback = ''}) {
  if (v == null) return fallback;
  return v.toString();
}

List<String> _asStringList(dynamic v) {
  if (v is List) {
    return v.where((e) => e != null).map((e) => e.toString()).toList();
  }
  return const [];
}

class ReasoningSummaryV1 {
  final String version;

  // context
  final String caseTitle;
  final String nodeId;
  final EndTag tag;
  final int turn;

  // accuse / reason
  final String accused; // suspect id or name
  final String reasonMode; // choice/text/voice
  final List<String> reasonIds;
  final List<String> selectedObservations;
  final String reasonText;
  final String reasonSummary;

  // evidence
  final List<String> cluesPreview;

  // scoring
  final ReasoningLevel level;
  final int score;
  final int threshold;
  final String engineMessage;

  final List<String> matchedEvidence;
  final List<String> missingKeyEvidence;

  const ReasoningSummaryV1({
    required this.version,
    required this.caseTitle,
    required this.nodeId,
    required this.tag,
    required this.turn,
    required this.accused,
    required this.reasonMode,
    required this.reasonIds,
    required this.selectedObservations,
    required this.reasonText,
    required this.reasonSummary,
    required this.cluesPreview,
    required this.level,
    required this.score,
    required this.threshold,
    required this.engineMessage,
    required this.matchedEvidence,
    required this.missingKeyEvidence,
  });

  factory ReasoningSummaryV1.fromMap(Map<String, dynamic> map) {
    return ReasoningSummaryV1(
      version: _asString(map['version']),
      caseTitle: _asString(map['case_title']),
      nodeId: _asString(map['node_id']),
      tag: endTagFrom(_asString(map['tag'])),
      turn: _asInt(map['turn']),
      accused: _asString(map['accused']),
      reasonMode: _asString(map['reason_mode'], fallback: 'choice'),
      reasonIds: _asStringList(map['reason_ids']),
      selectedObservations: _asStringList(map['selected_observations']),
      reasonText: _asString(map['reason_text']),
      reasonSummary: _asString(map['reason_summary']),
      cluesPreview: _asStringList(map['clues_preview']),
      level: reasoningLevelFrom(_asString(map['level'])),
      score: _asInt(map['score']),
      threshold: _asInt(map['threshold']),
      engineMessage: _asString(map['engine_message']),
      matchedEvidence: _asStringList(map['matched_evidence']),
      missingKeyEvidence: _asStringList(map['missing_key_evidence']),
    );
  }

  /// 支援後端回傳 meta 可能是 Stringified JSON 的狀況（保守）
  static ReasoningSummaryV1? tryParse(dynamic meta) {
    if (meta == null) return null;

    if (meta is Map<String, dynamic>) {
      return ReasoningSummaryV1.fromMap(meta);
    }
    if (meta is Map) {
      return ReasoningSummaryV1.fromMap(meta.map((k, v) => MapEntry(k.toString(), v)));
    }
    if (meta is String) {
      final s = meta.trim();
      if (s.isEmpty) return null;
      try {
        final obj = jsonDecode(s);
        if (obj is Map) {
          return ReasoningSummaryV1.fromMap(obj.map((k, v) => MapEntry(k.toString(), v)));
        }
      } catch (_) {}
    }
    return null;
  }

  bool get isV1 => version.trim() == kReasoningContractV1;

  @override
  String toString() => 'ReasoningSummaryV1(tag=$tag level=$level score=$score/$threshold)';
}
