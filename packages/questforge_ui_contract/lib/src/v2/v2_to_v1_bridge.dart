// lib/src/v2/v2_to_v1_bridge.dart
import '../commands.dart'; // v1
import '../reasoning_summary_v1.dart'; // v1 meta
import '../utils.dart';

// v2
import 'show_end_screen_command_v2.dart';

/// Bridge v2 command -> v1 SessionCommand (minimal UI change strategy).
///
/// Today we only bridge:
/// - ShowEndScreenCommandV2 -> ShowEndScreenCommand (v1)
class V2ToV1Bridge {
  static SessionCommand? bridgeShowEndScreen(ShowEndScreenCommandV2 v2) {
    final summary = v2.summary;

    // Build a v1 ReasoningSummaryV1 from v2 summary (best-effort)
    final meta = _mapSummaryToV1(summary);

    return ShowEndScreenCommand(
      type: CommandType.showEndScreen,
      nodeId: asString(v2.end.meta?['node_id']),
      tag: asString(v2.end.meta?['tag']),
      title: v2.end.title,
      narration: v2.end.narration,
      lesson: List<String>.from(v2.end.lessons),
      options: v2.actions
          .map((a) => EndOption(id: a.id, text: a.text))
          .toList(growable: false),
      meta: meta,
    );
  }

  static ReasoningSummaryV1 _mapSummaryToV1(dynamic v2Summary) {
    if (v2Summary == null) return const ReasoningSummaryV1();

    // 你 v1 ReasoningSummaryV1 是強型別，這裡用它的 JSON 介面 best-effort 組一個 map 再 fromJson
    final m = <String, dynamic>{
      'version': 'reasoning_contract_v1',
      'case_title': v2Summary.caseTitle,
      'turn': v2Summary.turn,
      'accused': v2Summary.accused,
      'reason_mode': v2Summary.reason.mode,
      'reason_ids': v2Summary.reason.selectedObservationIds,
      'selected_observations': v2Summary.reason.selectedObservationIds, // v2 沒有文字版就先塞 id
      'reason_text': v2Summary.reason.text,
      'reason_summary': v2Summary.reason.text.isNotEmpty
          ? v2Summary.reason.text
          : v2Summary.reason.selectedObservationIds.join('、'),
      'clues_preview': v2Summary.cluesPreview,
      'level': v2Summary.evaluation.level,
      'score': v2Summary.evaluation.score,
      'threshold': v2Summary.evaluation.threshold,
      'engine_message': v2Summary.evaluation.engineMessage,
      'matched_evidence': v2Summary.matchedEvidence.map((e) => e.text).toList(),
      'missing_key_evidence': v2Summary.missingKeyEvidence.map((e) => e.text).toList(),
    };

    return ReasoningSummaryV1.fromJson(m);
  }
}
