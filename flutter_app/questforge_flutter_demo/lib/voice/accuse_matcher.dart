// lib/game/voice/accuse_matcher.dart
import 'package:questforge_ui_contract/questforge_contract.dart';

class AccuseMatcher {
  /// 回傳要選的 choiceIndex；找不到回 null
  static int? matchChoiceIndex({
    required String recognized,
    required List<ChoiceView> choices,
  }) {
    final text = _norm(recognized);
    if (text.isEmpty) return null;

    // 交給老師 / 不確定
    if (_hasAny(text, const ['交給老師', '老師', '不確定', '不知道', '還沒想好', '我還不確定'])) {
      return _findByContains(choices, const ['交給老師', '我還不確定']);
    }

    // 常見：說出角色名或特徵
    // 你這案：飯糰啵啵 / 甜甜圈阿咚 / 鉛筆小刺
    final map = <List<String>, List<String>>{
      // 可能的語音說法 -> 用 choices text 去找包含
      ['飯糰', '啵啵', '白色吊飾', '白吊飾']: ['飯糰', '啵啵', '白色吊飾'],
      ['甜甜圈', '阿咚', '餅乾', '餅乾放旁邊']: ['甜甜圈', '阿咚', '餅乾'],
      ['鉛筆', '小刺', '橡皮擦', '找橡皮擦']: ['鉛筆', '小刺', '橡皮擦'],
    };

    for (final entry in map.entries) {
      final said = entry.key;
      final targetTokens = entry.value;
      if (_hasAny(text, said)) {
        final idx = _findByContains(choices, targetTokens);
        if (idx != null) return idx;
      }
    }

    // fallback：如果孩子講到 choice text 本身的一部分
    for (final c in choices) {
      final ct = _norm(c.text);
      if (ct.isNotEmpty && text.contains(ct)) return c.index;
    }

    return null;
  }

  static int? _findByContains(List<ChoiceView> choices, List<String> tokens) {
    for (final c in choices) {
      final t = _norm(c.text);
      if (_hasAny(t, tokens)) return c.index;
    }
    return null;
  }

  static bool _hasAny(String s, List<String> tokens) {
    for (final k in tokens) {
      final kk = _norm(k);
      if (kk.isNotEmpty && s.contains(kk)) return true;
    }
    return false;
  }

  static String _norm(String s) {
    return (s)
        .trim()
        .toLowerCase()
        .replaceAll('（', '(')
        .replaceAll('）', ')')
        .replaceAll(RegExp(r'\s+'), '');
  }
}
