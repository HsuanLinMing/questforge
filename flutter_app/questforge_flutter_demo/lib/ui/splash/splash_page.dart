// lib/ui/splash/splash_page.dart
import 'dart:async';

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
  // ── poll config ──────────────────────────────────────────────
  static const _pollInterval = Duration(seconds: 2);
  static const _pollTimeout = Duration(seconds: 40); // 最長等 40 秒
  static const _minSplashDur = Duration(milliseconds: 1200); // 至少顯示 1.2s

  String _status = '初始化中…';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _initApp());
  }

  // ─────────────────────────────────────────────────────────────
  // Main init flow
  // ─────────────────────────────────────────────────────────────
  Future<void> _initApp() async {
    final api = FastApiBridge(baseUrl: AppEnv.apiBaseUrl);
    final startTime = DateTime.now();

    PreloadResp? preload;

    try {
      // ① Call /preload → picks story, creates session, kicks off TTS
      _setStatus('選取故事…');
      preload = await api.preload();

      debugPrint(
        '[Splash] preload ok source=${preload.storySource} '
        'id=${preload.storyId} fp=${preload.viewFp} count=${preload.preloadCount}',
      );

      // ② Poll /tts_status until scene_01_start is fully ready (or timeout)
      if (preload.viewFp.isNotEmpty && preload.preloadCount > 0) {
        _setStatus('準備語音…');
        await _pollUntilReady(
          api: api,
          viewFp: preload.viewFp,
          count: preload.preloadCount,
        );
      }
    } catch (e) {
      debugPrint('[Splash] Init error: $e');
      // Fall through – open menu anyway so user isn't stuck
    }

    // ③ Ensure minimum splash display time (UX)
    final elapsed = DateTime.now().difference(startTime);
    if (elapsed < _minSplashDur) {
      await Future<void>.delayed(_minSplashDur - elapsed);
    }

    if (!mounted) return;

    _setStatus('進入選單…');

    final hasAiStory = preload?.storySource == 'ai';

    Navigator.of(context).pushReplacement(
      PageRouteBuilder(
        transitionDuration: const Duration(milliseconds: 800),
        pageBuilder: (_, __, ___) => MainMenuPage(
          api: api,
          hasAiStory: hasAiStory,
        ),
        transitionsBuilder: (_, anim, __, child) =>
            FadeTransition(opacity: anim, child: child),
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────
  // Poll /tts_status until ready_count == count or timeout
  // ─────────────────────────────────────────────────────────────
  Future<void> _pollUntilReady({
    required FastApiBridge api,
    required String viewFp,
    required int count,
  }) async {
    final deadline = DateTime.now().add(_pollTimeout);

    while (DateTime.now().isBefore(deadline)) {
      try {
        final status = await api.fetchTtsStatus(viewFp: viewFp, count: count);
        debugPrint(
          '[Splash] TTS poll ready=${status.readyCount}/$count '
          'missing=${status.missing.length}',
        );

        if (mounted) {
          _setStatus('語音準備中（${status.readyCount}/$count）…');
        }

        if (status.ready || status.readyCount >= count) {
          debugPrint('[Splash] TTS all ready ✅');
          return;
        }
      } catch (e) {
        debugPrint('[Splash] TTS poll error: $e');
      }

      await Future<void>.delayed(_pollInterval);
    }

    debugPrint('[Splash] TTS poll timeout – proceeding anyway');
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
          // ① Background fill (cover)
          Image.asset(
            'assets/splash/splash_launch.png',
            fit: BoxFit.cover,
            alignment: Alignment.topCenter,
          ),

          // ② Crisp top-aligned version (no H-crop)
          Align(
            alignment: Alignment.topCenter,
            child: Image.asset(
              'assets/splash/splash_launch.png',
              fit: BoxFit.fitWidth,
              width: MediaQuery.of(context).size.width,
            ),
          ),

          // ③ Status bar at the bottom
          Align(
            alignment: Alignment.bottomCenter,
            child: Padding(
              padding: const EdgeInsets.only(bottom: 48),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const SizedBox(
                    width: 24,
                    height: 24,
                    child: CircularProgressIndicator(
                      strokeWidth: 2.5,
                      valueColor: AlwaysStoppedAnimation<Color>(Colors.white70),
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
