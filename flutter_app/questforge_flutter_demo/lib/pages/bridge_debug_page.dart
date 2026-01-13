import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:questforge_ui_contract/questforge_contract.dart';

import '../dev/python_bridge.dart';

class BridgeDebugPage extends StatefulWidget {
  const BridgeDebugPage({super.key});

  static final PythonBridge bridge = PythonBridge();

  @override
  State<BridgeDebugPage> createState() => _BridgeDebugPageState();
}

class _BridgeDebugPageState extends State<BridgeDebugPage> {
  Map<String, dynamic>? _lastRaw;

  NodeView? _view;
  List<CommandV2> _commands = const [];

  String _log = '';

  // flutter run -d macos --dart-define=QF_WORKDIR=/Users/user/Projects/QUESTFORGE
  static const String _workingDir = String.fromEnvironment('QF_WORKDIR', defaultValue: '');

  @override
  void initState() {
    super.initState();

    BridgeDebugPage.bridge.outputs.listen((m) {
      setState(() {
        _lastRaw = m;

        final t = (m['type'] ?? '').toString();
        if (t == 'log' || t == 'stderr' || t == 'exit' || t == 'bridge_started' || t == 'start_error' || t == 'hello' || t == 'error') {
          _log = '$_log\n${const JsonEncoder.withIndent('  ').convert(m)}';
          return;
        }

        try {
          // ✅ Day21-5：只吃 v2 envelope 的 step_result
          final stepV2 = StepResultParserV2.parse(m);
          if (stepV2 == null) {
            // 非 v2 或不是 step_result，就當 log 觀察
            _log = '$_log\n(unparsed)\n${const JsonEncoder.withIndent('  ').convert(m)}';
            return;
          }

          _view = stepV2.view;
          _commands = stepV2.commands;
        } catch (e) {
          _log = '$_log\nParse failed: $e\n${const JsonEncoder.withIndent('  ').convert(m)}';
        }
      });
    });
  }

  @override
  void dispose() {
    BridgeDebugPage.bridge.dispose();
    super.dispose();
  }

  Future<void> _startAndHello() async {
    if (_workingDir.trim().isEmpty) {
      setState(() {
        _log = '請用 dart-define 設定 QF_WORKDIR（QuestForge 專案根目錄絕對路徑）\n'
            '例：flutter run -d macos --dart-define=QF_WORKDIR=/Users/user/Projects/QUESTFORGE';
      });
      return;
    }

    setState(() => _log = 'Starting python bridge...\nworkingDir=$_workingDir');

    try {
      await BridgeDebugPage.bridge.start(
        workingDir: _workingDir,
        pythonBin: '$_workingDir/.venv/bin/python',
      );

      // hello
      BridgeDebugPage.bridge.send({'type': 'replay'});
    } catch (e) {
      setState(() => _log = '$_log\nstart() failed: $e');
    }
  }

  void _sendChoose(int choiceIndex) {
    BridgeDebugPage.bridge.send({'type': 'choose', 'choice_index': choiceIndex});
  }

  @override
  Widget build(BuildContext context) {
    final view = _view;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Day21 Bridge Debug (v2)'),
        actions: [
          IconButton(
            onPressed: BridgeDebugPage.bridge.isRunning ? BridgeDebugPage.bridge.stop : _startAndHello,
            icon: Icon(BridgeDebugPage.bridge.isRunning ? Icons.stop : Icons.play_arrow),
            tooltip: BridgeDebugPage.bridge.isRunning ? 'Stop' : 'Start+Hello',
          ),
        ],
      ),
      body: ListView(
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
              return Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: FilledButton.tonal(
                  onPressed: c.enabled ? () => _sendChoose(c.index) : null,
                  child: Text('${c.index}. ${c.text}'),
                ),
              );
            }),
          ],
          const Divider(height: 32),
          Text('Commands (${_commands.length})', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          ..._commands.map((c) {
            if (c is ShowEndScreenCommandV2) {
              return Card(
                child: ListTile(
                  title: Text('show_end_screen(v2): ${c.end.title}'),
                  subtitle: Text('actions: ${c.actions.map((e) => e.id).join(', ')}'),
                  onTap: () async {
                    await Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => _EndScreenPreviewPageV2(cmd: c)),
                    );
                  },
                ),
              );
            }

            return ListTile(
              title: Text(c.type),
              subtitle: Text(const JsonEncoder.withIndent('  ').convert(c.toJson())),
            );
          }),
          const Divider(height: 32),
          Text('Last raw', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          SelectableText(_lastRaw == null ? '—' : const JsonEncoder.withIndent('  ').convert(_lastRaw)),
          const Divider(height: 32),
          Text('Log', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          SelectableText(_log.isEmpty ? '—' : _log),
        ],
      ),
    );
  }
}

class _EndScreenPreviewPageV2 extends StatelessWidget {
  const _EndScreenPreviewPageV2({required this.cmd});

  final ShowEndScreenCommandV2 cmd;

  @override
  Widget build(BuildContext context) {
    final end = cmd.end;
    final reasoning = cmd.summary;

    return Scaffold(
      appBar: AppBar(title: Text(end.title.isEmpty ? 'EndScreen' : end.title)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(end.narration),
          const SizedBox(height: 16),

          if (end.lessons.isNotEmpty) ...[
            Text('今天學到的', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            ...end.lessons.map(
              (e) => Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text('• $e'),
              ),
            ),
            const SizedBox(height: 16),
          ],

          if (reasoning != null) ...[
            Text('理由整理（v2）', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(
              reasoning.reason.text.isNotEmpty
                  ? reasoning.reason.text
                  : reasoning.reason.selectedObservationIds.join('、'),
            ),
            const SizedBox(height: 12),
            Text(
              '成熟度：${reasoning.evaluation.level}  '
              '${reasoning.evaluation.threshold > 0 ? "${reasoning.evaluation.score}/${reasoning.evaluation.threshold}" : ""}'.trim(),
            ),
            if (reasoning.evaluation.engineMessage.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(reasoning.evaluation.engineMessage),
              ),
            const SizedBox(height: 16),
          ],

          Text('接下來要做什麼？', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),

          ...cmd.actions.map((a) {
            return Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: FilledButton(
                onPressed: () {
                  // ✅ v2 回傳：ui_action
                  BridgeDebugPage.bridge.send({
                    'type': 'ui_action',
                    'payload': {
                      'kind': a.kind, // "end_flow"
                      'id': a.id, // go_epilogue / restart_case / ...
                      if (a.data != null) 'data': a.data,
                    },
                  });

                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('已送出 ui_action：${a.kind}/${a.id}')),
                  );
                },
                child: Text(a.text),
              ),
            );
          }),
        ],
      ),
    );
  }
}
