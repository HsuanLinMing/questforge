// lib/core/contracts/session_commands.dart
import 'dart:convert';

import 'reasoning_contract_v1.dart';

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

List<T> _asList<T>(dynamic v, T Function(dynamic) mapFn) {
  if (v is List) return v.map(mapFn).toList();
  return <T>[];
}

Map<String, dynamic> _asMap(dynamic v) {
  if (v is Map<String, dynamic>) return v;
  if (v is Map) return v.map((k, val) => MapEntry(k.toString(), val));
  if (v is String) {
    final s = v.trim();
    if (s.isEmpty) return <String, dynamic>{};
    try {
      final obj = jsonDecode(s);
      if (obj is Map) return obj.map((k, val) => MapEntry(k.toString(), val));
    } catch (_) {}
  }
  return <String, dynamic>{};
}

enum SessionCommandType {
  askReason,
  showReasoningFeedback,
  showEndScreen,
  confirmQuiz,
  flow,
  unknown,
}

SessionCommandType cmdTypeFrom(String? s) {
  switch ((s ?? '').trim()) {
    case 'ask_reason':
      return SessionCommandType.askReason;
    case 'show_reasoning_feedback':
      return SessionCommandType.showReasoningFeedback;
    case 'show_end_screen':
      return SessionCommandType.showEndScreen;
    case 'confirm_quiz':
      return SessionCommandType.confirmQuiz;
    case 'flow':
      return SessionCommandType.flow;
    default:
      return SessionCommandType.unknown;
  }
}

/// ---- ask_reason ----

enum ReasonInputMode { choice, text, voice }

ReasonInputMode reasonInputModeFrom(String? s) {
  switch ((s ?? '').trim()) {
    case 'choice':
      return ReasonInputMode.choice;
    case 'text':
      return ReasonInputMode.text;
    case 'voice':
      return ReasonInputMode.voice;
    default:
      return ReasonInputMode.text; // engine fallback voice->text
  }
}

class ReasonOption {
  final String id;
  final String text;
  final List<String> expectedEvidence;

  const ReasonOption({
    required this.id,
    required this.text,
    required this.expectedEvidence,
  });

  factory ReasonOption.fromMap(Map<String, dynamic> map) {
    return ReasonOption(
      id: _asString(map['id']),
      text: _asString(map['text']),
      expectedEvidence: _asList(map['expected_evidence'], (e) => e?.toString() ?? '').where((e) => e.isNotEmpty).toList(),
    );
  }
}

class AskReasonCommand {
  final ReasonInputMode mode;
  final String title;
  final String hint;
  final int maxLen;
  final List<ReasonOption> options;

  const AskReasonCommand({
    required this.mode,
    required this.title,
    required this.hint,
    required this.maxLen,
    required this.options,
  });

  factory AskReasonCommand.fromMap(Map<String, dynamic> map) {
    return AskReasonCommand(
      mode: reasonInputModeFrom(_asString(map['mode'], fallback: 'text')),
      title: _asString(map['title']),
      hint: _asString(map['hint']),
      maxLen: _asInt(map['max_len'], fallback: 80),
      options: _asList(map['options'], (e) => ReasonOption.fromMap(_asMap(e))),
    );
  }
}

/// ---- show_reasoning_feedback ----

class ShowReasoningFeedbackCommand {
  final String text;
  final ReasoningSummaryV1? meta;

  const ShowReasoningFeedbackCommand({
    required this.text,
    required this.meta,
  });

  factory ShowReasoningFeedbackCommand.fromMap(Map<String, dynamic> map) {
    return ShowReasoningFeedbackCommand(
      text: _asString(map['text']),
      meta: ReasoningSummaryV1.tryParse(map['meta']),
    );
  }
}

/// ---- show_end_screen ----

class EndScreenOption {
  final String id;
  final String text;

  const EndScreenOption({required this.id, required this.text});

  factory EndScreenOption.fromMap(Map<String, dynamic> map) {
    return EndScreenOption(
      id: _asString(map['id']),
      text: _asString(map['text']),
    );
  }
}

class ShowEndScreenCommand {
  final String nodeId;
  final String tag; // keep raw tag for UI routing if needed
  final String title;
  final String narration;
  final List<String> lesson;
  final List<EndScreenOption> options;
  final ReasoningSummaryV1? meta;

  const ShowEndScreenCommand({
    required this.nodeId,
    required this.tag,
    required this.title,
    required this.narration,
    required this.lesson,
    required this.options,
    required this.meta,
  });

  factory ShowEndScreenCommand.fromMap(Map<String, dynamic> map) {
    return ShowEndScreenCommand(
      nodeId: _asString(map['node_id']),
      tag: _asString(map['tag']),
      title: _asString(map['title']),
      narration: _asString(map['narration']),
      lesson: _asList(map['lesson'], (e) => e?.toString() ?? '').where((e) => e.isNotEmpty).toList(),
      options: _asList(map['options'], (e) => EndScreenOption.fromMap(_asMap(e))),
      meta: ReasoningSummaryV1.tryParse(map['meta']),
    );
  }
}

/// ---- confirm_quiz ----
/// Day19-E 先不猜 quiz schema，保留 raw list，等你 Day? 把 quiz contract 固定再建型別。
class ConfirmQuizCommand {
  final List<dynamic> quizRaw;

  const ConfirmQuizCommand({required this.quizRaw});

  factory ConfirmQuizCommand.fromMap(Map<String, dynamic> map) {
    final q = map['quiz'];
    return ConfirmQuizCommand(quizRaw: (q is List) ? q : const []);
  }
}

/// ---- flow ----

class FlowCommand {
  final String action; // restart_case/switch_case/quit/go_epilogue...
  const FlowCommand({required this.action});

  factory FlowCommand.fromMap(Map<String, dynamic> map) {
    return FlowCommand(action: _asString(map['action']));
  }
}

/// ---- union wrapper ----

class SessionCommand {
  final SessionCommandType type;
  final Map<String, dynamic> raw;

  final AskReasonCommand? askReason;
  final ShowReasoningFeedbackCommand? reasoningFeedback;
  final ShowEndScreenCommand? endScreen;
  final ConfirmQuizCommand? confirmQuiz;
  final FlowCommand? flow;

  const SessionCommand._({
    required this.type,
    required this.raw,
    this.askReason,
    this.reasoningFeedback,
    this.endScreen,
    this.confirmQuiz,
    this.flow,
  });

  factory SessionCommand.fromDynamic(dynamic cmd) {
    final map = _asMap(cmd);
    final t = cmdTypeFrom(_asString(map['type']));
    switch (t) {
      case SessionCommandType.askReason:
        return SessionCommand._(type: t, raw: map, askReason: AskReasonCommand.fromMap(map));
      case SessionCommandType.showReasoningFeedback:
        return SessionCommand._(type: t, raw: map, reasoningFeedback: ShowReasoningFeedbackCommand.fromMap(map));
      case SessionCommandType.showEndScreen:
        return SessionCommand._(type: t, raw: map, endScreen: ShowEndScreenCommand.fromMap(map));
      case SessionCommandType.confirmQuiz:
        return SessionCommand._(type: t, raw: map, confirmQuiz: ConfirmQuizCommand.fromMap(map));
      case SessionCommandType.flow:
        return SessionCommand._(type: t, raw: map, flow: FlowCommand.fromMap(map));
      case SessionCommandType.unknown:
        return SessionCommand._(type: t, raw: map);
    }
  }

  static List<SessionCommand> parseList(dynamic commands) {
    if (commands is List) {
      return commands.map(SessionCommand.fromDynamic).toList();
    }
    return const [];
  }
}
