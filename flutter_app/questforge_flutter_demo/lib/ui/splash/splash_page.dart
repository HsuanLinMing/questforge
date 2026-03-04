// lib/ui/splash/splash_page.dart
import 'package:flutter/material.dart';

import 'package:questforge_flutter_demo/config/app_env.dart';
import 'package:questforge_flutter_demo/fastapi_bridge.dart';
import 'package:questforge_flutter_demo/ui/menu/main_menu_page.dart';

class SplashPage extends StatefulWidget {
  const SplashPage({super.key});

  @override
  State<SplashPage> createState() => _SplashPageState();
}

class _SplashPageState extends State<SplashPage> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
    _initApp();
  });
  }

  Future<void> _initApp() async {
    // 這裡可以做 TTS 預熱、呼叫 backend initialize_stories 等等
    try {
      final api = FastApiBridge(baseUrl: AppEnv.apiBaseUrl);
      final resp = await api.initializeStories();

      // 假設有 AI 故事就傳 true，沒有就 false
      final hasAiStory = resp.hasAiStories;

      if (!mounted) return;

      // 動畫過渡到 MainMenuPage
      Navigator.of(context).pushReplacement(
        PageRouteBuilder(
          transitionDuration: const Duration(milliseconds: 800),
          pageBuilder: (_, __, ___) => MainMenuPage(
            api: api,
            hasAiStory: hasAiStory,
          ),
          transitionsBuilder: (_, anim, __, child) {
            return FadeTransition(opacity: anim, child: child);
          },
        ),
      );
    } catch (e) {
      debugPrint('[SplashPage] Init error: $e');
      // 如果失敗也進主畫面，可以讓主畫面顯示錯誤或重試
      if (mounted) {
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (_) => MainMenuPage(
              api: FastApiBridge(baseUrl: AppEnv.apiBaseUrl),
              hasAiStory: false,
            ),
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      // ✅ 不要白色，先用接近天空的顏色（你也可以改成 Color(0xFFBFE6FF) 之類）
      backgroundColor: const Color(0xFFBFE6FF),
      body: Stack(
        fit: StackFit.expand,
        children: [
          // ① 底層：用 cover 填滿整個螢幕（允許裁切）
          //    目的：把上下空白補起來，視覺不會白邊
          Image.asset(
            'assets/splash/splash_launch.png',
            fit: BoxFit.cover,
            alignment: Alignment.topCenter,
          ),

          // ② 上層：用 fitWidth 保證「左右不裁切」
          Align(
            alignment: Alignment.topCenter,
            child: Image.asset(
              'assets/splash/splash_launch.png',
              fit: BoxFit.fitWidth,
              width: MediaQuery.of(context).size.width, // ✅ 關鍵：確保用螢幕寬
            ),
          ),
        ],
      ),
    );
  }
}
