// lib/dev/bridge/command_router.dart
import 'package:questforge_ui_contract/questforge_contract.dart';

class CommandBundle {
  final AskReasonCommandV2? ask;
  final ConfirmQuizCommandV2? quiz;
  final ShowEndScreenCommandV2? end;

  const CommandBundle({
    this.ask,
    this.quiz,
    this.end,
  });

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
      if (c is ShowEndScreenCommandV2) end = c;
      if (c is AskReasonCommandV2) ask = c;
      if (c is ConfirmQuizCommandV2) quiz = c;
    }

    // ✅ Day23-B：End 優先互斥
    if (end != null) {
      ask = null;
      quiz = null;
    }

    return CommandBundle(
      ask: ask,
      quiz: quiz,
      end: end,
    );
  }
}
