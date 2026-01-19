// lib/dev/bridge/bridge_debug_page.dart
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'package:questforge_flutter_demo/bridge/overlay_manager.dart';
import 'package:questforge_flutter_demo/fastapi_bridge.dart';
import '../bridge/bridge_controller_v2.dart';


class BridgeDebugPage extends StatefulWidget {
  const BridgeDebugPage({super.key});

  @override
  State<BridgeDebugPage> createState() => _BridgeDebugPageState();
}

class _BridgeDebugPageState extends State<BridgeDebugPage>
    with WidgetsBindingObserver {
  final OverlayManagerV2 _overlays = const OverlayManagerV2();
  late final BridgeControllerV2 _controller;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);

    final api = FastApiBridge(baseUrl: 'http://127.0.0.1:8003');

    _controller = BridgeControllerV2(
      api: api,
      kindToWire: _uiActionKindToWire,
    );

    // ✅ FastAPI：start() 會直接打 /start 拿第一包
    _controller.start();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _controller.dispose();
    super.dispose();
  }

  String _uiActionKindToWire(Object? kind) {
    final s = kind?.toString() ?? '';
    if (s.contains('end_flow') || s.contains('endFlow')) return 'end_flow';
    return s.split('.').last;
  }

  void _newGame() {
    // 目前 controller.start() 已經會 new session，
    // 這裡做成「再開一次」：簡單就 stop 再 start
    _controller.stop();
    _controller.start();

    if (kDebugMode) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('已送出：start（new game）')),
      );
    }
  }

  String _clip(String s, [int n = 4000]) =>
      s.length <= n ? s : '${s.substring(0, n)}\n...(${s.length} chars)';

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
            _controller.sendSetReasons(reasonIds: ids, text: text ?? '');
          },
          onCloseAsk: () {},

          // ConfirmQuiz
          onSubmitQuiz: (answers) {
            _controller.sendConfirmQuiz(answers);
          },
          onCloseQuiz: () {
           _controller.sendConfirmQuiz(const <Object?>[], skipped: true);
          },

          // EndScreen
          endLockVN: _controller.endActionLockVN,
          pendingEndVN: _controller.pendingEndActionIdVN,
          onTapEndAction: (action) {
            final ok = _controller.sendEndActionSpec(action);
            if (!ok) return;

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
            _controller.unlockEndAction();
          },
        );

        return Scaffold(
          appBar: AppBar(
            title: const Text('Bridge Debug (FastAPI)'),
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
            ],
          ),
          body: Stack(
            children: [
              ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  if (view == null) ...[
                    const Text('尚未收到 view（請按右上 New Game）'),
                    const SizedBox(height: 12),
                  ] else ...[
                    Text(view.title,
                        style: Theme.of(context).textTheme.titleLarge),
                    const SizedBox(height: 8),
                    Text(view.narration),
                    const SizedBox(height: 12),
                    ...view.choices.map((c) {
                      final disabled = overlayShowing || !c.enabled;
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: FilledButton.tonal(
                          onPressed: disabled
                              ? null
                              : () => _controller.sendChoose(c.index),
                          child: Text('${c.index}. ${c.text}'),
                        ),
                      );
                    }),
                  ],
                  const Divider(height: 32),
                  Text('Commands (${state.commands.length})',
                      style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  ...state.commands.map((c) {
                    return ListTile(
                      title: Text(c.type),
                      subtitle: Text(const JsonEncoder.withIndent('  ')
                          .convert(c.toJson())),
                    );
                  }),
                  const Divider(height: 32),
                  Text('Snapshot',
                      style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  SelectableText(
                    const JsonEncoder.withIndent('  ')
                        .convert(state.snapshot.toJson()),
                  ),
                  const Divider(height: 32),
                  Text('Last raw',
                      style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  SelectableText(
                    state.lastRaw == null ? '—' : _clip(jsonEncode(state.lastRaw)),
                  ),
                ],
              ),

              if (overlay != null) overlay,
            ],
          ),
        );
      },
    );
  }
}
