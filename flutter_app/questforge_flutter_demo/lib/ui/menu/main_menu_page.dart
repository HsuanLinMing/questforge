import 'package:flutter/material.dart';

import 'package:questforge_flutter_demo/bridge/bridge_controller_v2.dart';
import 'package:questforge_flutter_demo/fastapi_bridge.dart';
import 'package:questforge_flutter_demo/game/game_page_v1.dart';

class MainMenuPage extends StatefulWidget {
  const MainMenuPage({
    super.key,
    required this.api,
    required this.hasAiStory,
  });

  final FastApiBridge api;
  final bool hasAiStory;

  @override
  State<MainMenuPage> createState() => _MainMenuPageState();
}

class _MainMenuPageState extends State<MainMenuPage> {
  late BridgeControllerV2 _controller;
  bool _starting = false;

  @override
  void initState() {
    super.initState();
    _controller = BridgeControllerV2(
      api: widget.api,
      kindToWire: (k) {
        final s = k?.toString() ?? '';
        if (s.contains('end_flow') || s.contains('endFlow')) return 'end_flow';
        return s.split('.').last;
      },
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _startGame() async {
    if (_starting) return;
    setState(() => _starting = true);

    try {
      _controller.start();

      if (!mounted) return;

      // Navigate to GamePageV1
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => Scaffold(
            appBar: AppBar(
              title: const Text('QuestForge'),
              leading: IconButton(
                icon: const Icon(Icons.arrow_back),
                onPressed: () {
                  _controller.stop();
                  Navigator.of(context).pop();
                },
              ),
              actions: [
                IconButton(
                  icon: const Icon(Icons.restart_alt),
                  tooltip: 'New Game',
                  onPressed: () {
                    _controller.stop();
                    _controller.start();
                  },
                ),
              ],
            ),
            body: GamePageV1(controller: _controller),
          ),
        ),
      );
    } catch (e) {
      debugPrint('[MainMenu] Start game error: $e');
    } finally {
      if (mounted) {
        setState(() => _starting = false);
      }
    }
  }

  Future<void> _resumeStory() async {
    // 您可以決定 Resume 和 Start 後端是不是帶不同的參數，
    // 或者直接呼叫相同的 start() 讓後端來決定。
    await _startGame();
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
            // 使用 fill 將導致按鈕圖片跟隨 180x56 拉伸，若原圖並非此比例則會變形。
            // 但如果使用 contain ，會在左右或上下留白。
            // 對於按鈕的框架來說，填滿 (fill) 或寬度適配 (fitWidth) 較不會有空白的瑕疵。
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
          // Background Image
          Positioned.fill(
            child: Image.asset(
              'assets/menu/bg_main_menu.png',
              // 如果 1024x1536 要完全填滿現在的手機，一定會經歷裁切。
              // cover 會保持比例並且裁掉超出的寬度(或是高度)。
              fit: BoxFit.fitWidth, // ⭐ 關鍵改這個
              alignment: Alignment.topCenter,
            ),
          ),

          SafeArea(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // 標題或留白
                const Spacer(),

                // 按鈕區 (置左下角)
                Padding(
                  padding: const EdgeInsets.only(left: 32.0, bottom: 48.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (widget.hasAiStory) ...[
                        _buildGlassButton(
                          text: '繼續遊玩',
                          imagePath: 'assets/menu/btn_glass_green.png',
                          onTap: _resumeStory,
                        ),
                        const SizedBox(height: 16),
                      ],
                      _buildGlassButton(
                        text: widget.hasAiStory ? '新遊戲' : '開始遊戲',
                        imagePath: 'assets/menu/btn_glass_blue.png',
                        onTap: _startGame,
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

          // 讀取中的遮罩
          if (_starting)
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
