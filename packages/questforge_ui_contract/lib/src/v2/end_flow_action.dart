// lib/src/v2/end_flow_action.dart
import 'ui_action.dart';
import 'actions.dart';

class EndFlowActionV2 extends UiActionV2 {
  EndFlowActionV2({required super.id, super.data})
      : super(kind: UiActionKindV2.endFlow);
}
