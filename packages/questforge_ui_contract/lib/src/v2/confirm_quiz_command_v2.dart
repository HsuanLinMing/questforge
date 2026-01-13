// packages/questforge_ui_contract/lib/src/v2/confirm_quiz_command_v2.dart
import '../utils.dart';
import 'command_base_v2.dart';

class ConfirmQuizCommandV2 extends CommandV2 {
   ConfirmQuizCommandV2({
    required this.quiz,
  });

  /// keep flexible (engine-defined)
  final List<Object?> quiz;

  @override
  String get type => 'confirm_quiz';

  static ConfirmQuizCommandV2 fromJson(Map<String, dynamic> m) {
    final q = pick(m, 'quiz');
    return ConfirmQuizCommandV2(
      quiz: (q is List) ? List<Object?>.from(q) : const <Object?>[],
    );
  }

  @override
  Map<String, dynamic> toJson() => <String, dynamic>{
        'type': type,
        'quiz': List<Object?>.from(quiz),
      };
}
