import 'reasoning_summary_v1.dart';
import 'utils.dart';

/// Command types emitted by engine.
/// Keep in sync with Python:
/// - ask_reason
/// - confirm_quiz
/// - show_reasoning_feedback
/// - show_end_screen
/// - flow
enum CommandType {
  askReason,
  confirmQuiz,
  showReasoningFeedback,
  showEndScreen,
  flow,
  unknown;

  static CommandType fromString(String v) {
    switch (v.trim()) {
      case 'ask_reason':
        return CommandType.askReason;
      case 'confirm_quiz':
        return CommandType.confirmQuiz;
      case 'show_reasoning_feedback':
        return CommandType.showReasoningFeedback;
      case 'show_end_screen':
        return CommandType.showEndScreen;
      case 'flow':
        return CommandType.flow;
      default:
        return CommandType.unknown;
    }
  }

  String get value => switch (this) {
        CommandType.askReason => 'ask_reason',
        CommandType.confirmQuiz => 'confirm_quiz',
        CommandType.showReasoningFeedback => 'show_reasoning_feedback',
        CommandType.showEndScreen => 'show_end_screen',
        CommandType.flow => 'flow',
        CommandType.unknown => 'unknown',
      };
}

/// Base class for all commands.
sealed class SessionCommand implements JsonCodable {
  const SessionCommand({required this.type});

  final CommandType type;

  static SessionCommand fromJson(Object? json) {
    final m = normalizeJsonMap(json);
    final t = CommandType.fromString(asString(pick(m, 'type')));
    switch (t) {
      case CommandType.askReason:
        return AskReasonCommand.fromJson(m);
      case CommandType.confirmQuiz:
        return ConfirmQuizCommand.fromJson(m);
      case CommandType.showReasoningFeedback:
        return ShowReasoningFeedbackCommand.fromJson(m);
      case CommandType.showEndScreen:
        return ShowEndScreenCommand.fromJson(m);
      case CommandType.flow:
        return FlowCommand.fromJson(m);
      case CommandType.unknown:
        return UnknownCommand.fromJson(m);
    }
  }
}

/// ask_reason
/// Engine payload:
/// {
///   "type": "ask_reason",
///   "mode": "choice"|"text",
///   "options": [...],
///   "title": "...",
///   "hint": "...",
///   "max_len": 80
/// }
class AskReasonCommand extends SessionCommand {
  const AskReasonCommand({
    required super.type,
    required this.mode,
    required this.options,
    required this.title,
    required this.hint,
    required this.maxLen,
  });

  final String mode; // choice|text
  final List<ReasonOption> options;
  final String title;
  final String hint;
  final int maxLen;

  static AskReasonCommand fromJson(JsonMap m) {
    return AskReasonCommand(
      type: CommandType.askReason,
      mode: asString(pick(m, 'mode'), 'choice'),
      options: asListOf<ReasonOption>(pick(m, 'options'), ReasonOption.fromJson),
      title: asString(pick(m, 'title')),
      hint: asString(pick(m, 'hint')),
      maxLen: asInt(pick(m, 'max_len'), 80),
    );
  }

  @override
  JsonMap toJson() => <String, dynamic>{
        'type': type.value,
        'mode': mode,
        'options': options.map((e) => e.toJson()).toList(growable: false),
        'title': title,
        'hint': hint,
        'max_len': maxLen,
      };
}

class ReasonOption implements JsonCodable {
  const ReasonOption({
    this.id = '',
    this.text = '',
    this.expectedEvidence = const <String>[],
  });

  final String id;
  final String text;
  final List<String> expectedEvidence; // optional (if provided by case config)

  static ReasonOption fromJson(Object? json) {
    final m = normalizeJsonMap(json);
    return ReasonOption(
      id: asString(pick(m, 'id')),
      text: asString(pick(m, 'text')),
      expectedEvidence:
          asListOf<String>(pick(m, 'expected_evidence'), (x) => asString(x)),
    );
  }

  @override
  JsonMap toJson() => <String, dynamic>{
        'id': id,
        'text': text,
        'expected_evidence': List<String>.from(expectedEvidence),
      };
}

/// confirm_quiz
/// { "type":"confirm_quiz", "quiz":[...] }
class ConfirmQuizCommand extends SessionCommand {
  const ConfirmQuizCommand({
    required super.type,
    required this.quiz,
  });

  final List<Object?> quiz; // keep flexible (engine-defined)

  static ConfirmQuizCommand fromJson(JsonMap m) {
    final q = pick(m, 'quiz');
    return ConfirmQuizCommand(
      type: CommandType.confirmQuiz,
      quiz: (q is List) ? List<Object?>.from(q) : const <Object?>[],
    );
  }

  @override
  JsonMap toJson() => <String, dynamic>{
        'type': type.value,
        'quiz': List<Object?>.from(quiz),
      };
}

/// show_reasoning_feedback
/// { "type":"show_reasoning_feedback", "text":"...", "meta": {contract v1} }
class ShowReasoningFeedbackCommand extends SessionCommand {
  const ShowReasoningFeedbackCommand({
    required super.type,
    required this.text,
    required this.meta,
  });

  final String text;
  final ReasoningSummaryV1 meta;

  static ShowReasoningFeedbackCommand fromJson(JsonMap m) {
    return ShowReasoningFeedbackCommand(
      type: CommandType.showReasoningFeedback,
      text: asString(pick(m, 'text')),
      meta: ReasoningSummaryV1.fromJson(pick(m, 'meta')),
    );
  }

  @override
  JsonMap toJson() => <String, dynamic>{
        'type': type.value,
        'text': text,
        'meta': meta.toJson(),
      };
}

/// show_end_screen
/// Engine payload:
/// {
///   "type": "show_end_screen",
///   "node_id": "...",
///   "tag": "ending_result|ending_wrong|epilogue",
///   "title": "...",
///   "narration": "...",
///   "lesson": [...],
///   "options": [{"id":"go_epilogue","text":"進入尾聲"}, ...],
///   "meta": {contract v1}
/// }
class ShowEndScreenCommand extends SessionCommand {
  const ShowEndScreenCommand({
    required super.type,
    required this.nodeId,
    required this.tag,
    required this.title,
    required this.narration,
    required this.lesson,
    required this.options,
    required this.meta,
  });

  final String nodeId;
  final String tag;
  final String title;
  final String narration;
  final List<String> lesson;
  final List<EndOption> options;
  final ReasoningSummaryV1 meta;

  static ShowEndScreenCommand fromJson(JsonMap m) {
    return ShowEndScreenCommand(
      type: CommandType.showEndScreen,
      nodeId: asString(pick(m, 'node_id')),
      tag: asString(pick(m, 'tag')),
      title: asString(pick(m, 'title')),
      narration: asString(pick(m, 'narration')),
      lesson: asListOf<String>(pick(m, 'lesson'), (x) => asString(x)),
      options: asListOf<EndOption>(pick(m, 'options'), EndOption.fromJson),
      meta: ReasoningSummaryV1.fromJson(pick(m, 'meta')),
    );
  }

  @override
  JsonMap toJson() => <String, dynamic>{
        'type': type.value,
        'node_id': nodeId,
        'tag': tag,
        'title': title,
        'narration': narration,
        'lesson': List<String>.from(lesson),
        'options': options.map((e) => e.toJson()).toList(growable: false),
        'meta': meta.toJson(),
      };
}

class EndOption implements JsonCodable {
  const EndOption({this.id = '', this.text = ''});

  final String id; // go_epilogue | restart_case | switch_case | quit
  final String text;

  static EndOption fromJson(Object? json) {
    final m = normalizeJsonMap(json);
    return EndOption(
      id: asString(pick(m, 'id')),
      text: asString(pick(m, 'text')),
    );
  }

  @override
  JsonMap toJson() => <String, dynamic>{
        'id': id,
        'text': text,
      };
}

/// flow
/// { "type":"flow", "action":"restart_case|switch_case|quit" }
class FlowCommand extends SessionCommand {
  const FlowCommand({required super.type, required this.action});

  final String action;

  static FlowCommand fromJson(JsonMap m) {
    return FlowCommand(
      type: CommandType.flow,
      action: asString(pick(m, 'action')),
    );
  }

  @override
  JsonMap toJson() => <String, dynamic>{
        'type': type.value,
        'action': action,
      };
}

/// Unknown command: keep raw payload for forward compatibility.
class UnknownCommand extends SessionCommand {
  const UnknownCommand({
    required super.type,
    required this.rawType,
    required this.raw,
  });

  final String rawType;
  final JsonMap raw;

  static UnknownCommand fromJson(JsonMap m) {
    return UnknownCommand(
      type: CommandType.unknown,
      rawType: asString(pick(m, 'type')),
      raw: m,
    );
  }

  @override
  JsonMap toJson() => raw;
}
