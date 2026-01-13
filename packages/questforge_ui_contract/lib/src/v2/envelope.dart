// lib/src/v2/envelope.dart
import 'contract_version.dart';

/// Optional but recommended:
/// - Flutter / Python 都可以用同一層封包
/// - type: "step_result" / "command" / "event" / "ui_action"
class ContractEnvelopeV2 {
  final String contractVersion;
  final String type;
  final Map<String, dynamic> payload;

  const ContractEnvelopeV2({
    required this.contractVersion,
    required this.type,
    required this.payload,
  });

  factory ContractEnvelopeV2.fromJson(Map<String, dynamic> json) {
    return ContractEnvelopeV2(
      contractVersion: (json['contract_version'] ?? '').toString(),
      type: (json['type'] ?? '').toString(),
      payload: (json['payload'] as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{},
    );
  }

  Map<String, dynamic> toJson() => {
        'contract_version': contractVersion.isEmpty ? UiContractV2.version : contractVersion,
        'type': type,
        'payload': payload,
      };
}
