// lib/src/v2/step_result_parser_v2.dart
import '../utils.dart';
import 'contract_version.dart';
import 'envelope.dart';
import 'step_result_v2.dart';

class StepResultParserV2 {
  static StepResultV2? parse(Object? json) {
    final m = normalizeJsonMap(json);
    final cv = asString(pick(m, 'contract_version'));
    if (cv != UiContractV2.version) return null;

    final env = ContractEnvelopeV2.fromJson(m);
    if (env.type == 'step_result') {
      return StepResultV2.fromPayload(env.payload);
    }
    return null;
  }
}
