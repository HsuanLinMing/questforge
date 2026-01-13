// lib/src/step_result_parser.dart
import 'utils.dart';
import 'step_result.dart';
import 'commands.dart';
import 'node_view.dart';

// v2
import 'v2/contract_version.dart';
import 'v2/envelope.dart';
import 'v2/commands_v2.dart';
import 'v2/command_base_v2.dart';
import 'v2/show_end_screen_command_v2.dart';
import 'v2/v2_to_v1_bridge.dart';

/// Unified parse entry for both v1 and v2.
///
/// Rule:
/// - If contract_version == ui_contract_v2:
///   - treat as ContractEnvelopeV2 {contract_version,type,payload}
///   - we bridge v2 commands -> v1 SessionCommand so existing Flutter UI can keep working.
/// - Else:
///   - legacy v1 StepResult JSON (existing behavior)
class StepResultParser {
  static StepResult parse(Object? json) {
    final m = normalizeJsonMap(json);

    final contract = asString(pick(m, 'contract_version'));
    if (contract == UiContractV2.version) {
      return _parseV2(m);
    }

    return StepResult.fromJson(json);
  }

  static StepResult _parseV2(JsonMap root) {
    // v2 currently: envelope-style
    // {
    //   "contract_version":"ui_contract_v2",
    //   "type":"command"|"step_result"|...,
    //   "payload": {...}
    // }
    final env = ContractEnvelopeV2.fromJson(root);

    switch (env.type) {
      case 'command':
        final v2cmd = _tryParseV2Command(env.payload);
        final v1cmd = (v2cmd == null) ? null : _bridgeV2CommandToV1(v2cmd);

        return StepResult(
          view: null,
          events: const <String>[],
          isOver: false,
          selectedChoiceIndex: 0,
          selectedNext: '',
          commands: v1cmd == null ? const <SessionCommand>[] : <SessionCommand>[v1cmd],
        );

      case 'step_result':
        return _parseV2StepResultPayload(env.payload);

      default:
        return const StepResult(commands: <SessionCommand>[]);
    }
  }

  static StepResult _parseV2StepResultPayload(Map<String, dynamic> payload) {
    // For future-proofing:
    // payload may look like v1 step_result (view/events/is_over/commands),
    // but commands are v2 commands.
    final v = pick(payload, 'view');
    final view = (v == null) ? null : NodeView.fromJson(v);

    final events = asListOf<String>(pick(payload, 'events'), (x) => asString(x));

    final isOver = asBool(pick(payload, 'is_over'), false);

    final selectedChoiceIndex = asInt(pick(payload, 'selected_choice_index'));
    final selectedNext = asString(pick(payload, 'selected_next'));

    final commandsRaw = pick(payload, 'commands');
    final out = <SessionCommand>[];

    if (commandsRaw is List) {
      for (final x in commandsRaw) {
        final cm = normalizeJsonMap(x);

        // 1) try v2 command -> bridge -> v1
        final v2cmd = _tryParseV2Command(cm);
        if (v2cmd != null) {
          final v1cmd = _bridgeV2CommandToV1(v2cmd);
          if (v1cmd != null) out.add(v1cmd);
          continue;
        }

        // 2) fallback: treat as legacy v1 command
        try {
          out.add(SessionCommand.fromJson(cm));
        } catch (_) {
          // ignore unknown
        }
      }
    }

    return StepResult(
      view: view,
      events: events,
      isOver: isOver,
      selectedChoiceIndex: selectedChoiceIndex,
      selectedNext: selectedNext,
      commands: out,
    );
  }

  static CommandV2? _tryParseV2Command(Map<String, dynamic> json) {
    return CommandParserV2.tryFromJson(json);
  }

  static SessionCommand? _bridgeV2CommandToV1(CommandV2 cmd) {
    if (cmd is ShowEndScreenCommandV2) {
      return V2ToV1Bridge.bridgeShowEndScreen(cmd);
    }

    // future: add more bridges here (ask_reason/confirm_quiz/feedback)
    return null;
  }
}
