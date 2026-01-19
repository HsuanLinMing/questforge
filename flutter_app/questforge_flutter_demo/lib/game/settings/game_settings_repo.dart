// lib/game/settings/game_settings_repo.dart
import 'package:shared_preferences/shared_preferences.dart';

class GameSettingsRepo {
  static const String _kTtsRate = 'qf_tts_rate_v1';

  /// 建議值：0.35 ~ 0.65，預設 0.45
  Future<double> loadTtsRate({double fallback = 0.45}) async {
    try {
      final sp = await SharedPreferences.getInstance();
      final v = sp.getDouble(_kTtsRate);
      if (v == null) return fallback;
      return v;
    } catch (_) {
      return fallback;
    }
  }

  Future<void> saveTtsRate(double rate) async {
    try {
      final sp = await SharedPreferences.getInstance();
      await sp.setDouble(_kTtsRate, rate);
    } catch (_) {
      // ignore
    }
  }
}
