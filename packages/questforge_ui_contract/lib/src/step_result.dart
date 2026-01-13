import 'commands.dart';
import 'node_view.dart';
import 'utils.dart';

/// Mirror of Python StepResult (engine -> UI).
class StepResult implements JsonCodable {
  const StepResult({
    this.view,
    this.events = const <String>[],
    this.isOver = false,
    this.selectedChoiceIndex = 0,
    this.selectedNext = '',
    this.commands = const <SessionCommand>[],
  });

  final NodeView? view;
  final List<String> events;
  final bool isOver;

  final int selectedChoiceIndex;
  final String selectedNext;

  final List<SessionCommand> commands;

  static StepResult fromJson(Object? json) {
    final m = normalizeJsonMap(json);
    final v = pick(m, 'view');
    return StepResult(
      view: (v == null) ? null : NodeView.fromJson(v),
      events: asListOf<String>(pick(m, 'events'), (x) => asString(x)),
      isOver: asBool(pick(m, 'is_over'), false),
      selectedChoiceIndex: asInt(pick(m, 'selected_choice_index')),
      selectedNext: asString(pick(m, 'selected_next')),
      commands: asListOf<SessionCommand>(
        pick(m, 'commands'),
        (x) => SessionCommand.fromJson(x),
      ),
    );
  }

  @override
  JsonMap toJson() => <String, dynamic>{
        'view': view?.toJson(),
        'events': List<String>.from(events),
        'is_over': isOver,
        'selected_choice_index': selectedChoiceIndex,
        'selected_next': selectedNext,
        'commands': commands.map((e) => e.toJson()).toList(growable: false),
      };
}
