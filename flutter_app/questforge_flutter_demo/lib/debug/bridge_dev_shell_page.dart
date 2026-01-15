// lib/debug/bridge_dev_shell_page.dart
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:questforge_flutter_demo/bridge/bridge_controller_v2.dart';
import 'package:questforge_flutter_demo/dev/python_bridge.dart';

import '../game/game_page_v1.dart';
import 'debug_panel_v2.dart';

class BridgeDevShellPage extends StatefulWidget {
  const BridgeDevShellPage({super.key});

  static final PythonBridge bridge = PythonBridge();

  @override
  State<BridgeDevShellPage> createState() => _BridgeDevShellPageState();
}

class _BridgeDevShellPageState extends State<BridgeDevShellPage> {
  // flutter run -d macos --dart-define=QF_WORKDIR=/Users/user/Projects/QUESTFORGE
  static const String _workingDir = String.fromEnvironment('QF_WORKDIR', defaultValue: '');

  late final BridgeControllerV2 _controller;

  @override
  void initState() {
    super.initState();
    _controller = BridgeControllerV2(
      bridge: BridgeDevShellPage.bridge,
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

  Future<void> _startAndHello() async {
    if (_workingDir.trim().isEmpty) {
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        const SnackBar(content: Text('請用 dart-define 設定 QF_WORKDIR（QuestForge 專案根目錄絕對路徑）')),
      );
      return;
    }

    try {
      await BridgeDevShellPage.bridge.start(
        workingDir: _workingDir,
        pythonBin: '$_workingDir/.venv/bin/python',
      );
      _controller.sender.sendReplay();
    } catch (e) {
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        SnackBar(content: Text('start() failed: $e')),
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
            onPressed: BridgeDevShellPage.bridge.isRunning ? BridgeDevShellPage.bridge.stop : _startAndHello,
            icon: Icon(BridgeDevShellPage.bridge.isRunning ? Icons.stop : Icons.play_arrow),
            tooltip: BridgeDevShellPage.bridge.isRunning ? 'Stop' : 'Start+Hello',
          ),
          IconButton(
            onPressed: BridgeDevShellPage.bridge.isRunning ? _controller.sender.sendReplay : null,
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

      // ✅ 正式遊玩 UI（不含 debug 文本）
      body: GamePageV1(controller: _controller),

      // ✅ Debug only
      endDrawer: canOpenDebug ? DebugPanelV2(controller: _controller) : null,
    );
  }
}
