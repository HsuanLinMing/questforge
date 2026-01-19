// lib/debug/bridge_dev_shell_page.dart
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'package:questforge_flutter_demo/bridge/bridge_controller_v2.dart';
import 'package:questforge_flutter_demo/fastapi_bridge.dart';


import '../game/game_page_v1.dart';
import 'debug_panel_v2.dart';

class BridgeDevShellPage extends StatefulWidget {
  const BridgeDevShellPage({super.key});

  @override
  State<BridgeDevShellPage> createState() => _BridgeDevShellPageState();
}

class _BridgeDevShellPageState extends State<BridgeDevShellPage> {
  late final BridgeControllerV2 _controller;

  @override
  void initState() {
    super.initState();

    final api = FastApiBridge(baseUrl: 'http://127.0.0.1:8003');

    _controller = BridgeControllerV2(
      api: api,
      kindToWire: _uiActionKindToWire,
    );

    _controller.start();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  String _uiActionKindToWire(Object? kind) {
    final s = kind?.toString() ?? '';
    if (s.contains('end_flow') || s.contains('endFlow')) return 'end_flow';
    return s.split('.').last;
  }

  void _newGame() {
    _controller.stop();
    _controller.start();
    if (kDebugMode) {
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        const SnackBar(content: Text('已送出：start（new game）')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final canOpenDebug = kDebugMode;

    return Scaffold(
      appBar: AppBar(
        title: const Text('QuestForge'),
        actions: [
          IconButton(
            onPressed: _newGame,
            icon: const Icon(Icons.play_arrow),
            tooltip: 'New Game (/start)',
          ),
          IconButton(
            onPressed: _controller.sendReplay,
            icon: const Icon(Icons.replay),
            tooltip: 'Replay',
          ),
          if (canOpenDebug)
            Builder(
              builder: (ctx) => IconButton(
                icon: const Icon(Icons.bug_report),
                tooltip: 'Debug Panel',
                onPressed: () => Scaffold.of(ctx).openEndDrawer(),
              ),
            ),
        ],
      ),

      body: GamePageV1(controller: _controller),

      endDrawer: canOpenDebug ? DebugPanelV2(controller: _controller) : null,
    );
  }
}
