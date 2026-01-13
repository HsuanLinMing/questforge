// lib/src/v2/step_result_v2.dart
import '../utils.dart';
import '../node_view.dart';
import 'command_base_v2.dart';
import 'commands_v2.dart';

class StepResultV2 {
  const StepResultV2({
    this.view,
    this.events = const <String>[],
    this.isOver = false,
    this.selectedChoiceIndex = 0,
    this.selectedNext = '',
    this.commands = const <CommandV2>[],
  });

  final NodeView? view;
  final List<String> events;
  final bool isOver;
  final int selectedChoiceIndex;
  final String selectedNext;
  final List<CommandV2> commands;

  static StepResultV2 fromPayload(Map<String, dynamic> payload) {
    final v = pick(payload, 'view');
    final view = (v == null) ? null : NodeView.fromJson(v);

    final events = asListOf<String>(pick(payload, 'events'), (x) => asString(x));
    final isOver = asBool(pick(payload, 'is_over'), false);

    final selectedChoiceIndex = asInt(pick(payload, 'selected_choice_index'));
    final selectedNext = asString(pick(payload, 'selected_next'));

    final raw = pick(payload, 'commands');
    final out = <CommandV2>[];
    if (raw is List) {
      for (final x in raw) {
        final m = normalizeJsonMap(x);
        final cmd = CommandParserV2.tryFromJson(m);
        if (cmd != null) out.add(cmd);
      }
    }

    return StepResultV2(
      view: view,
      events: events,
      isOver: isOver,
      selectedChoiceIndex: selectedChoiceIndex,
      selectedNext: selectedNext,
      commands: out,
    );
  }
}
