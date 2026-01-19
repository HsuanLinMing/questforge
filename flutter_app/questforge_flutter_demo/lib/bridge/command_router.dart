// lib/dev/bridge/command_router.dart
import 'package:questforge_ui_contract/questforge_contract.dart';

class CommandBundle {
  final AskReasonCommandV2? ask;
  final ConfirmQuizCommandV2? quiz;
  final ShowEndScreenCommandV2? end;

  const CommandBundle({this.ask, this.quiz, this.end});

  List<String> get types {
    final out = <String>[];
    if (end != null) out.add(end!.type);
    if (ask != null) out.add(ask!.type);
    if (quiz != null) out.add(quiz!.type);
    return out;
  }

  CommandBundle copyWith({
    AskReasonCommandV2? ask,
    ConfirmQuizCommandV2? quiz,
    ShowEndScreenCommandV2? end,
  }) {
    return CommandBundle(
      ask: ask ?? this.ask,
      quiz: quiz ?? this.quiz,
      end: end ?? this.end,
    );
  }
}

class CommandRouterV2 {
  const CommandRouterV2();

  CommandBundle parse(List<CommandV2> commands) {
    AskReasonCommandV2? ask;
    ConfirmQuizCommandV2? quiz;
    ShowEndScreenCommandV2? end;

    for (final c in commands) {
      final t = (c.type).trim();
      final raw0 = c.toJson();

      if (t == 'show_end_screen') {
        final raw = _normalizeShowEndScreenToV2(raw0);
        end = _safeParse(() => ShowEndScreenCommandV2.fromJson(raw));
      } else if (t == 'ask_reason') {
        // ✅ 暫時忽略 ask_reason：先讓主流程恢復
        // ask = _safeParse(() => AskReasonCommandV2.fromJson(raw0));
        continue;
      } else if (t == 'confirm_quiz') {
        quiz = _safeParse(() => ConfirmQuizCommandV2.fromJson(raw0));
      }
    }

    // end 的優先權最高
    if (end != null) {
      ask = null;
      quiz = null;
    }

    return CommandBundle(ask: ask, quiz: quiz, end: end);
  }

  T? _safeParse<T>(T Function() fn) {
    try {
      return fn();
    } catch (_) {
      return null;
    }
  }

  /// ✅ 後端目前送的是 v1：
  /// {
  ///   type:"show_end_screen",
  ///   node_id, tag,
  ///   title, narration,
  ///   lesson: [...],
  ///   options:[{id,text}...],
  ///   meta:{reason_* / score / threshold ...}
  /// }
  ///
  /// Flutter UI contract 用 v2：
  /// {
  ///   type:"show_end_screen",
  ///   node_id, tag,
  ///   end:{title,narration,lessons},
  ///   summary:{...ReasoningSummaryV2...},
  ///   actions:[{kind,id,text,data}]
  /// }
  Map<String, dynamic> _normalizeShowEndScreenToV2(Map<String, dynamic> raw) {
    // 已是 v2 就直接回傳
    if (raw['end'] is Map && raw['actions'] is List) return raw;

    final meta = (raw['meta'] is Map) ? (raw['meta'] as Map).cast<String, dynamic>() : <String, dynamic>{};

    final lessonList = (raw['lesson'] ?? raw['lessons']);
    final lessons = (lessonList is List) ? lessonList.map((e) => e.toString()).toList() : <String>[];

    final optionsList = (raw['options'] ?? raw['actions']);
    final options = (optionsList is List) ? optionsList : const <Object?>[];

    final actions = <Map<String, dynamic>>[];
    for (final o in options) {
      if (o is! Map) continue;
      final m = o.cast<String, dynamic>();
      actions.add({
        'kind': 'end_flow',
        'id': (m['id'] ?? '').toString(),
        'text': (m['text'] ?? '').toString(),
        'data': m['data'], // 有就帶著，沒有就 null
      });
    }

    // evidence list 允許直接透傳（格式已經是 {id,text} 就能被 v2 解析）
    List<Map<String, dynamic>> _asEvidenceList(dynamic v) {
      if (v is! List) return const <Map<String, dynamic>>[];
      final out = <Map<String, dynamic>>[];
      for (final e in v) {
        if (e is Map) out.add(e.cast<String, dynamic>());
      }
      return out;
    }

    final summary = <String, dynamic>{
      'case_title': (meta['case_title'] ?? '').toString(),
      'turn': meta['turn'] ?? 0,
      'accused': (meta['accused'] ?? '').toString(),
      'reason': {
        'mode': (meta['reason_mode'] ?? '').toString(),
        'selected_observation_ids': (meta['reason_ids'] is List)
            ? (meta['reason_ids'] as List).map((e) => e.toString()).toList()
            : const <String>[],
        'text': (meta['reason_text'] ?? meta['reason_summary'] ?? '').toString(),
      },
      'clues_preview': (meta['clues_preview'] is List)
          ? (meta['clues_preview'] as List).map((e) => e.toString()).toList()
          : const <String>[],
      'evaluation': {
        'level': (meta['level'] ?? '').toString(),
        'score': meta['score'] ?? 0,
        'threshold': meta['threshold'] ?? 0,
        'engine_message': (meta['engine_message'] ?? '').toString(),
      },
      'matched_evidence': _asEvidenceList(meta['matched_evidence']),
      'missing_key_evidence': _asEvidenceList(meta['missing_key_evidence']),
    };

    return <String, dynamic>{
      'type': 'show_end_screen',
      'node_id': (raw['node_id'] ?? '').toString(),
      'tag': (raw['tag'] ?? '').toString(),
      'end': {
        'title': (raw['title'] ?? '').toString(),
        'narration': (raw['narration'] ?? '').toString(),
        'lessons': lessons,
      },
      'summary': summary,
      'actions': actions,
    };
  }
}
