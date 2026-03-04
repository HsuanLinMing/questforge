// lib/ui/splash/splash_page.dart
import 'dart:async';

import 'package:flutter/material.dart';

import 'package:questforge_flutter_demo/bridge/bridge_controller_v2.dart';
import 'package:questforge_flutter_demo/config/app_env.dart';
import 'package:questforge_flutter_demo/fastapi_bridge.dart';
import 'package:questforge_flutter_demo/ui/menu/main_menu_page.dart';

class SplashPage extends StatefulWidget {
  const SplashPage({super.key});

  @override
  State<SplashPage> createState() => _SplashPageState();
}

class _SplashPageState extends State<SplashPage> {
  // ── poll config ──────────────────────────────────────────────
  static const _pollInterval = Duration(seconds: 2);
  static const _pollTimeout = Duration(seconds: 120);
  static const _minSplashDur = Duration(milliseconds: 1200);

  String _status = '初始化中…';
  bool _showRetryButton = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _initApp());
  }

  // ─────────────────────────────────────────────────────────────
  // Main init flow
  // ─────────────────────────────────────────────────────────────
  Future<void> _initApp() async {
    setState(() => _showRetryButton = false);
    final startTime = DateTime.now();

    final api = FastApiBridge(baseUrl: AppEnv.apiBaseUrl);

    // ① Build the controller ONCE here – it will be passed all the way to GamePage
    final controller = BridgeControllerV2(
      api: api,
      kindToWire: (k) {
        final s = k?.toString() ?? '';
        if (s.contains('end_flow') || s.contains('endFlow')) return 'end_flow';
        return s.split('.').last;
      },
    );

    PreloadResp? preload;
    bool hasAiStory = false;

    try {
      // ② /preload: picks story (AI-first), creates session, kicks off TTS
      _setStatus('選取故事…');
      preload = await api.preload();

      hasAiStory = preload.storySource == 'ai';

      debugPrint(
        '[Splash] preload ok source=${preload.storySource} '
        'id=${preload.storyId} fp=${preload.viewFp} count=${preload.preloadCount}',
      );

      // ③ Poll until scene_01_start TTS fully ready (or timeout)
      if (preload.viewFp.isNotEmpty && preload.preloadCount > 0) {
        _setStatus('準備語音…');
        final ok = await _pollUntilTtsReady(
          api: api,
          viewFp: preload.viewFp,
          count: preload.preloadCount,
        );
        if (!ok) {
          _setStatus('語音準備超時，請檢查網路');
          setState(() => _showRetryButton = true);
          return; // Stop flow, let user retry
        }
      }

      // ④ Apply bundle directly – no extra /start call required
      controller.applyPreload(
        bundle: preload.bundle,
        sessionId: preload.sessionId,
        events: preload.events,
        isOver: preload.isOver,
      );
    } catch (e) {
      debugPrint('[Splash] Init error: $e');
      _setStatus('初始化失敗，請重試\n$e');
      setState(() => _showRetryButton = true);
      return; // Stop flow on hard error
    }

    // ⑤ Ensure minimum splash display time
    final elapsed = DateTime.now().difference(startTime);
    if (elapsed < _minSplashDur) {
      await Future<void>.delayed(_minSplashDur - elapsed);
    }

    if (!mounted) return;

    debugPrint(
        '[Splash] handoff controller hash=${identityHashCode(controller)} sess=${controller.sessionId}');

    Navigator.of(context).pushReplacement(
      PageRouteBuilder(
        transitionDuration: const Duration(milliseconds: 800),
        pageBuilder: (_, __, ___) => MainMenuPage(
          controller: controller,
          hasAiStory: hasAiStory,
        ),
        transitionsBuilder: (_, anim, __, child) =>
            FadeTransition(opacity: anim, child: child),
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────
  // Poll /tts_status until ready or timeout
  // ─────────────────────────────────────────────────────────────
  Future<bool> _pollUntilTtsReady({
    required FastApiBridge api,
    required String viewFp,
    required int count,
  }) async {
    final deadline = DateTime.now().add(_pollTimeout);

    while (DateTime.now().isBefore(deadline)) {
      try {
        final s = await api.fetchTtsStatus(viewFp: viewFp, count: count);
        debugPrint('[Splash] TTS poll ready=${s.readyCount}/$count');

        if (mounted) _setStatus('語音準備中（${s.readyCount}/$count）…');

        if (s.ready || s.readyCount >= count) {
          debugPrint('[Splash] TTS all ready ✅');
          return true;
        }
      } catch (e) {
        debugPrint('[Splash] TTS poll error: $e');
      }
      await Future<void>.delayed(_pollInterval);
    }
    debugPrint('[Splash] TTS poll timeout – wait failed');
    return false;
  }

  void _setStatus(String s) {
    if (!mounted) return;
    setState(() => _status = s);
  }

  // ─────────────────────────────────────────────────────────────
  // UI
  // ─────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFBFE6FF),
      body: Stack(
        fit: StackFit.expand,
        children: [
          Image.asset(
            'assets/splash/splash_launch.png',
            fit: BoxFit.cover,
            alignment: Alignment.topCenter,
          ),
          Align(
            alignment: Alignment.topCenter,
            child: Image.asset(
              'assets/splash/splash_launch.png',
              fit: BoxFit.fitWidth,
              width: MediaQuery.of(context).size.width,
            ),
          ),
          // Status indicator
          Align(
            alignment: Alignment.bottomCenter,
            child: Padding(
              padding: const EdgeInsets.only(bottom: 48),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (!_showRetryButton)
                    const SizedBox(
                      width: 24,
                      height: 24,
                      child: CircularProgressIndicator(
                        strokeWidth: 2.5,
                        valueColor:
                            AlwaysStoppedAnimation<Color>(Colors.white70),
                      ),
                    ),
                  if (_showRetryButton)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 16.0, top: 16.0),
                      child: ElevatedButton(
                        onPressed: _initApp,
                        child: const Text('重試'),
                      ),
                    ),
                  const SizedBox(height: 12),
                  Text(
                    _status,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 13,
                      shadows: [Shadow(blurRadius: 4)],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
