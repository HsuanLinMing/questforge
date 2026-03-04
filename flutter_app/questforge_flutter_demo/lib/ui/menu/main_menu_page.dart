// lib/ui/menu/main_menu_page.dart
import 'package:flutter/material.dart';

import 'package:questforge_flutter_demo/bridge/bridge_controller_v2.dart';
import 'package:questforge_flutter_demo/game/game_page_v1.dart';

/// ✅ MainMenuPage now accepts the already-started controller from Splash.
/// Pressing "開始遊戲" navigates directly into GamePage without calling start() again.
class MainMenuPage extends StatefulWidget {
  const MainMenuPage({
    super.key,
    required this.controller,
    required this.hasAiStory,
    // Legacy compat: still accepts api but ignores it
    this.api,
  });

  final BridgeControllerV2 controller;
  final bool hasAiStory;
  final Object? api; // kept for call-site backward compat

  @override
  State<MainMenuPage> createState() => _MainMenuPageState();
}

class _MainMenuPageState extends State<MainMenuPage> {
  bool _entering = false;

  Future<void> _enterGame() async {
    if (_entering) return;
    setState(() => _entering = true);

    try {
      debugPrint(
          '[Menu] start game controller hash=${identityHashCode(widget.controller)}');
      await Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => Scaffold(
            appBar: AppBar(
              title: const Text('QuestForge'),
              leading: IconButton(
                icon: const Icon(Icons.arrow_back),
                onPressed: () => Navigator.of(context).pop(),
              ),
              actions: [
                IconButton(
                  icon: const Icon(Icons.restart_alt),
                  tooltip: 'New Game',
                  onPressed: () {
                    widget.controller.stop();
                    widget.controller.start();
                  },
                ),
              ],
            ),
            body: GamePageV1(controller: widget.controller),
          ),
        ),
      );
    } finally {
      if (mounted) setState(() => _entering = false);
    }
  }

  void _openSettings() {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('設置功能尚未實作')),
    );
  }

  Widget _buildGlassButton({
    required String text,
    required String imagePath,
    required VoidCallback onTap,
  }) {
    final w = MediaQuery.of(context).size.width;
    final btnW = (w * 0.48).clamp(160.0, 220.0);
    final btnH = (btnW * 56 / 180).clamp(48.0, 70.0);

    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: btnW,
        height: btnH,
        decoration: BoxDecoration(
          image: DecorationImage(
            image: AssetImage(imagePath),
            fit: BoxFit.fill,
          ),
        ),
        alignment: Alignment.center,
        child: Text(
          text,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 18,
            fontWeight: FontWeight.w800,
            letterSpacing: 1.2,
            shadows: [
              Shadow(
                blurRadius: 4.0,
                color: Colors.black45,
                offset: Offset(0, 2),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Stack(
        children: [
          // Background
          Positioned.fill(
            child: Image.asset(
              'assets/menu/bg_main_menu.png',
              fit: BoxFit.fitWidth,
              alignment: Alignment.topCenter,
            ),
          ),

          SafeArea(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Spacer(),

                // Buttons
                Padding(
                  padding: const EdgeInsets.only(left: 32.0, bottom: 48.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (widget.hasAiStory) ...[
                        _buildGlassButton(
                          text: '繼續遊玩',
                          imagePath: 'assets/menu/btn_glass_green.png',
                          onTap: _enterGame,
                        ),
                        const SizedBox(height: 16),
                      ],
                      _buildGlassButton(
                        text: widget.hasAiStory ? '新遊戲' : '開始遊戲',
                        imagePath: 'assets/menu/btn_glass_blue.png',
                        onTap: _enterGame,
                      ),
                      const SizedBox(height: 16),
                      _buildGlassButton(
                        text: '設置',
                        imagePath: 'assets/menu/btn_glass_orange.png',
                        onTap: _openSettings,
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),

          // Loading overlay
          if (_entering)
            Container(
              color: Colors.black54,
              child: const Center(
                child: CircularProgressIndicator(color: Colors.white),
              ),
            ),
        ],
      ),
    );
  }
}
