// lib/dev/bridge/bridge_debug_page.dart
import 'dart:convert';
import 'package:flutter/foundation.dart';

import 'package:flutter/material.dart';
import 'package:questforge_flutter_demo/bridge/overlay_manager.dart';
import 'package:questforge_flutter_demo/dev/python_bridge.dart';

import '../bridge/bridge_controller_v2.dart';

class BridgeDebugPage extends StatefulWidget {
  const BridgeDebugPage({super.key});

  static final PythonBridge bridge = PythonBridge();

  @override
  State<BridgeDebugPage> createState() => _BridgeDebugPageState();
}

class _BridgeDebugPageState extends State<BridgeDebugPage> with WidgetsBindingObserver {
  // flutter run -d macos --dart-define=QF_WORKDIR=/Users/user/Projects/QUESTFORGE
  static const String _workingDir = String.fromEnvironment('QF_WORKDIR', defaultValue: '');

  final OverlayManagerV2 _overlays = const OverlayManagerV2();
  late final BridgeControllerV2 _controller;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);

    _controller = BridgeControllerV2(
      bridge: BridgeDebugPage.bridge,
      kindToWire: _uiActionKindToWire,
    );
    _controller.start();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _controller.dispose();

    // ⚠️ 如果 PythonBridge 是全域 singleton 且別頁也會用，這行拿掉
    BridgeDebugPage.bridge.dispose();

    super.dispose();
  }

  // enum / string -> wire string
  String _uiActionKindToWire(Object? kind) {
    final s = kind?.toString() ?? '';
    if (s.contains('end_flow') || s.contains('endFlow')) return 'end_flow';
    return s.split('.').last;
  }

  Future<void> _startAndHello() async {
    if (_workingDir.trim().isEmpty) {
      final messenger = ScaffoldMessenger.maybeOf(context);
      messenger?.showSnackBar(
        const SnackBar(
          content: Text('請用 dart-define 設定 QF_WORKDIR（QuestForge 專案根目錄絕對路徑）'),
        ),
      );
      return;
    }

    try {
      await BridgeDebugPage.bridge.start(
        workingDir: _workingDir,
        pythonBin: '$_workingDir/.venv/bin/python',
      );
      _controller.sender.sendReplay();
    } catch (e) {
      final messenger = ScaffoldMessenger.maybeOf(context);
      messenger?.showSnackBar(
        SnackBar(content: Text('start() failed: $e')),
      );
    }
  }

  String _clip(String s, [int n = 4000]) => s.length <= n ? s : '${s.substring(0, n)}\n...(${s.length} chars)';

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<BridgeUiStateV2>(
      valueListenable: _controller.stateVN,
      builder: (context, state, _) {
        final view = state.view;

        final ask = state.bundle.ask;
        final quiz = state.bundle.quiz;
        final end = state.bundle.end;

        final overlayShowing = (ask != null) || (quiz != null) || (end != null);

        final overlay = _overlays.buildOverlay(
          context: context,

          ask: ask,
          quiz: quiz,
          end: end,

          // AskReason
          onSubmitReasons: (ids, text) {
            _controller.sender.sendSetReasons(reasonIds: ids, text: text);
          },
          onCloseAsk: () {},

          // ConfirmQuiz
          onSubmitQuiz: (answers) {
            _controller.sender.sendConfirmQuizAnswerList(answers);
          },
          onCloseQuiz: () {
            _controller.sender.sendConfirmQuizAnswerList(
              const <Object?>[],
              skipped: true,
            );
          },

// EndScreen（✅ 收斂：只丟 spec，controller 負責 lock/timeout/send）
          endLockVN: _controller.endActionLockVN,
          pendingEndVN: _controller.pendingEndActionIdVN,
          onTapEndAction: (action) {
            final ok = _controller.sendEndActionSpec(action);
            if (!ok) return; // 被 lock 擋住

            if (kDebugMode) {
              final kind = (action.kind ?? '').toString();
              final id = (action.id ?? '').toString();
              final label = action.text;
              final msg = label.isNotEmpty ? '已送出：$label' : '已送出：$kind/$id';

              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text(msg)),
              );
            }
          },
          onCloseEnd: () {
            // 保險：避免 lock 卡死（你目前 showCloseButton=false 幾乎不會觸發）
            _controller.unlockEndAction();
          },
        );

        return Scaffold(
          appBar: AppBar(
            title: const Text('Day23 Bridge Debug (Controller v2)'),
            actions: [
              IconButton(
                onPressed: BridgeDebugPage.bridge.isRunning ? BridgeDebugPage.bridge.stop : _startAndHello,
                icon: Icon(
                  BridgeDebugPage.bridge.isRunning ? Icons.stop : Icons.play_arrow,
                ),
                tooltip: BridgeDebugPage.bridge.isRunning ? 'Stop' : 'Start+Hello',
              ),
              IconButton(
                onPressed: BridgeDebugPage.bridge.isRunning ? _controller.sender.sendReplay : null,
                icon: const Icon(Icons.replay),
                tooltip: 'Replay',
              ),
            ],
          ),
          body: Stack(
            children: [
              ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  if (view == null) ...[
                    const Text('尚未收到 view（請按右上 Start+Hello）'),
                    const SizedBox(height: 12),
                  ] else ...[
                    Text(view.title, style: Theme.of(context).textTheme.titleLarge),
                    const SizedBox(height: 8),
                    Text(view.narration),
                    const SizedBox(height: 12),
                    ...view.choices.map((c) {
                      final disabled = overlayShowing || !c.enabled;
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: FilledButton.tonal(
                          onPressed: disabled ? null : () => _controller.sender.sendChoose(c.index),
                          child: Text('${c.index}. ${c.text}'),
                        ),
                      );
                    }),
                  ],
                  const Divider(height: 32),
                  Text('Commands (${state.commands.length})', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  ...state.commands.map((c) {
                    return ListTile(
                      title: Text(c.type),
                      subtitle: Text(const JsonEncoder.withIndent('  ').convert(c.toJson())),
                    );
                  }),
                  const Divider(height: 32),
                  Text('Snapshot', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  SelectableText(
                    const JsonEncoder.withIndent('  ').convert(state.snapshot.toJson()),
                  ),
                  const Divider(height: 32),
                  Text('Last raw', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  SelectableText(
                    state.lastRaw == null ? '—' : _clip(jsonEncode(state.lastRaw)),
                  ),
                ],
              ),

              // ✅ overlays only
              if (overlay != null) overlay,
            ],
          ),
        );
      },
    );
  }
}
