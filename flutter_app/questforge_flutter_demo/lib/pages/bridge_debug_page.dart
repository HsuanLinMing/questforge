import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:questforge_ui_contract/questforge_contract.dart';

import '../debug/ask_reason_panel.dart';
import '../debug/confirm_quiz_panel.dart';
import '../dev/python_bridge.dart';

class BridgeDebugPage extends StatefulWidget {
  const BridgeDebugPage({super.key});

  static final PythonBridge bridge = PythonBridge();

  @override
  State<BridgeDebugPage> createState() => _BridgeDebugPageState();
}

class _BridgeDebugPageState extends State<BridgeDebugPage> with WidgetsBindingObserver {
  Map<String, dynamic>? _lastRaw;

  NodeView? _view;
  List<CommandV2> _commands = const <CommandV2>[];

  AskReasonCommandV2? _askReason;
  ConfirmQuizCommandV2? _confirmQuiz;

  // ✅ EndScreen single-layer controller
  bool _isEndScreenShowing = false;
  String _lastEndKey = ''; // 避免同一張 endscreen 重複 replace

  String _log = '';
  bool _uiJobScheduled = false;
  bool _active = true;
  VoidCallback? _pendingUiJob;
  // flutter run -d macos --dart-define=QF_WORKDIR=/Users/user/Projects/QUESTFORGE
  static const String _workingDir = String.fromEnvironment('QF_WORKDIR', defaultValue: '');

  @override
  void initState() {
    super.initState();

    BridgeDebugPage.bridge.outputs.listen((m) {
      if (!mounted) return;

      // ✅ 非前景時：不要 setState / 不要 append 巨量 log
      if (!_active) return;

      final t = (m['type'] ?? '').toString();
      if (t == 'ok' || t == 'log' || t == 'stderr' || t == 'exit' || t == 'bridge_started' || t == 'start_error' || t == 'hello' || t == 'error') {
        final line = jsonEncode(m); // ✅ 不縮排，便宜很多
        setState(() {
          _lastRaw = m;
          _appendLogLine(line);
        });
        return;
      }

      // ✅ 只吃 v2 envelope 的 step_result
      StepResultV2? stepV2;
      try {
        stepV2 = StepResultParserV2.parse(m);
      } catch (e) {
        final line = jsonEncode(m); // ✅ 不縮排，便宜很多
        setState(() {
          _lastRaw = m;
          _appendLogLine(line);
        });
        return;
      }

      if (stepV2 == null) {
        final line = jsonEncode(m); // ✅ 不縮排，便宜很多
        setState(() {
          _lastRaw = m;
          _appendLogLine(line);
        });
        return;
      }

      // ✅ 先更新狀態（不要在 build 做副作用）
      ShowEndScreenCommandV2? endScreen;
      AskReasonCommandV2? ask;
      ConfirmQuizCommandV2? quiz;

      for (final c in stepV2.commands) {
        if (endScreen == null && c is ShowEndScreenCommandV2) endScreen = c;
        if (ask == null && c is AskReasonCommandV2) ask = c;
        if (quiz == null && c is ConfirmQuizCommandV2) quiz = c;
      }

      final flowAction = _extractFlowActionFromRaw(m);
      if (flowAction != null) {
        debugPrint('[QF][FLOW][RAW] action=$flowAction');

        _scheduleUiJob(() => _handleFlowAction(flowAction));

        // ✅ flow 代表要重啟/換案/離開：通常就不要再跑 endscreen replace 了
        // return;  // 你想保守也可以不 return，但通常建議 return
      }

      setState(() {
        _lastRaw = m;

        _view = stepV2!.view;
        _commands = stepV2.commands;

        _askReason = ask;
        // ✅ 有 ask_reason 就不要同時顯示 confirm_quiz（避免雙層 overlay）
        _confirmQuiz = (ask == null) ? quiz : null;
      });

      // ✅ EndScreen：收到就自動開，而且只維持一層（pushReplacement）
      if (endScreen != null) {
        final endKey = _buildEndKey(endScreen!);
        if (endKey != _lastEndKey) {
          _lastEndKey = endKey;
          _scheduleUiJob(() => _openOrReplaceEndScreen(endScreen!));
        }
      }
    });
  }

  void _appendLogLine(String line) {
    const maxChars = 20000; // 你可以 1~5 萬自己調
    final next = '$_log\n$line';
    if (next.length <= maxChars) {
      _log = next;
    } else {
      _log = next.substring(next.length - maxChars);
    }
  }

  void _scheduleUiJob(VoidCallback job) {
    _pendingUiJob = job; // 永遠覆蓋成最新的
    if (_uiJobScheduled) return;
    _uiJobScheduled = true;

    WidgetsBinding.instance.addPostFrameCallback((_) {
      _uiJobScheduled = false;
      final j = _pendingUiJob;
      _pendingUiJob = null;
      if (!mounted || j == null) return;
      j();
    });
  }

// ✅ 直接從 raw step_result payload 裡抓 flow（不要依賴 contract parser）
  String? _extractFlowActionFromRaw(Map<String, dynamic> m) {
    try {
      if (m['contract_version'] != 'ui_contract_v2') return null;
      if (m['type'] != 'step_result') return null;

      final payload = (m['payload'] is Map) ? Map<String, dynamic>.from(m['payload']) : null;
      if (payload == null) return null;

      final commands = payload['commands'];
      if (commands is! List) return null;

      for (final c in commands) {
        if (c is Map && (c['type']?.toString() == 'flow')) {
          final action = (c['action'] ?? c['id'] ?? '').toString().trim();
          return action.isEmpty ? null : action;
        }
      }
      return null;
    } catch (_) {
      return null;
    }
  }

  void _handleFlowAction(String action) {
    debugPrint('[QF][FLOW] action=$action');

    // 先關掉 EndScreen（避免畫面停在尾聲按鈕）
    if (mounted) {
      Navigator.of(context, rootNavigator: true).maybePop();
    }

    // 再叫 python 真的做事（重啟/換案/離開）
    BridgeDebugPage.bridge.send({
      'type': 'apply_flow',
      'action': action,
    });

    if (action == 'quit' && mounted) {
      Navigator.of(context, rootNavigator: true).popUntil((r) => r.isFirst);
    }
  }

  String _buildEndKey(ShowEndScreenCommandV2 cmd) {
    final ids = cmd.actions.map((e) => e.id).join(',');
    return '${cmd.end.nodeId}|${cmd.end.title}|${cmd.end.narration.hashCode}|$ids';
  }

  // enum / string -> wire string
  String _uiActionKindToWire(Object? kind) {
    final s = kind?.toString() ?? '';
    if (s.contains('end_flow') || s.contains('endFlow')) return 'end_flow';
    return s.split('.').last; // 其他 type
  }

  Future<void> _openOrReplaceEndScreen(ShowEndScreenCommandV2 cmd) async {
    if (!mounted) return;

    final route = MaterialPageRoute(
      builder: (_) => _EndScreenPreviewPageV2(
        cmd: cmd,
        kindToWire: _uiActionKindToWire,
      ),
    );

    if (_isEndScreenShowing) {
      await Navigator.of(context).pushReplacement(route);
      return;
    }

    _isEndScreenShowing = true;
    await Navigator.of(context).push(route);
    _isEndScreenShowing = false;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // desktop 常見：inactive/paused/resumed
    _active = state == AppLifecycleState.resumed;
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
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

  void _sendSetReasons(List<String> ids, String text) {
    BridgeDebugPage.bridge.send({
      'type': 'set_reasons',
      'reason_ids': ids,
      'reason_text': text,
    });
  }

  void _sendConfirmQuizAnswer(List<Object?> answers, {bool skipped = false}) {
    BridgeDebugPage.bridge.send({
      'type': 'confirm_quiz_answer',
      'answers': answers,
      if (skipped) 'skipped': true,
    });
  }

  String _clip(String s, [int n = 4000]) => s.length <= n ? s : '${s.substring(0, n)}\n...(${s.length} chars)';

  @override
  Widget build(BuildContext context) {
    final view = _view;
    final ask = _askReason;
    final quiz = _confirmQuiz;
    final overlayShowing = (ask != null) || (quiz != null);

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
                      onPressed: disabled ? null : () => _sendChoose(c.index),
                      child: Text('${c.index}. ${c.text}'),
                    ),
                  );
                }),
              ],
              const Divider(height: 32),
              Text('Commands (${_commands.length})', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              ..._commands.map((c) {
                return ListTile(
                  title: Text(c.type),
                  subtitle: Text(const JsonEncoder.withIndent('  ').convert(c.toJson())),
                );
              }),
              const Divider(height: 32),
              Text('Last raw', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              SelectableText(_lastRaw == null ? '—' : _clip(jsonEncode(_lastRaw))),
              const Divider(height: 32),
              Text('Log', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              SelectableText(_log.isEmpty ? '—' : _clip(_log)),
            ],
          ),

          // ✅ ask_reason overlay：送 set_reasons
          if (ask != null)
            AskReasonPanel(
              command: ask,
              onSubmit: (ids, text) {
                _sendSetReasons(ids, text);
                setState(() => _askReason = null);
              },
              onClose: () => setState(() => _askReason = null),
            ),

          // ✅ confirm_quiz overlay：送 confirm_quiz_answer
          if (ask == null && quiz != null)
            ConfirmQuizPanel(
              command: quiz,
              onSubmit: (answers) {
                _sendConfirmQuizAnswer(answers);
                setState(() => _confirmQuiz = null);
              },
              onClose: () {
                _sendConfirmQuizAnswer(const <Object?>[], skipped: true);
                setState(() => _confirmQuiz = null);
              },
            ),
        ],
      ),
    );
  }
}

class _EndScreenPreviewPageV2 extends StatelessWidget {
  const _EndScreenPreviewPageV2({
    required this.cmd,
    required this.kindToWire,
  });

  final ShowEndScreenCommandV2 cmd;
  final String Function(Object? kind) kindToWire;

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
              reasoning.reason.text.isNotEmpty ? reasoning.reason.text : reasoning.reason.selectedObservationIds.join('、'),
            ),
            const SizedBox(height: 12),
            Text(
              '成熟度：${reasoning.evaluation.level}  '
                      '${reasoning.evaluation.threshold > 0 ? "${reasoning.evaluation.score}/${reasoning.evaluation.threshold}" : ""}'
                  .trim(),
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
                  final payload = {
                    'kind': kindToWire(a.kind),
                    'id': a.id,
                    'action': a.id,
                    if (a.data != null) 'data': a.data,
                  };
                  debugPrint('[QF][UI_ACTION][SEND_PAYLOAD] ${const JsonEncoder.withIndent('  ').convert(payload)}');
                  BridgeDebugPage.bridge.send({
                    'type': 'ui_action',
                    'payload': payload,
                  });
                  BridgeDebugPage.bridge.send({'type': 'replay'});
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text(
                        '已送出 ui_action：${kindToWire(a.kind)}/${a.id}',
                      ),
                    ),
                  );

                  // ✅ 不 pop：等引擎回下一個 show_end_screen，
                  //    BridgeDebugPage 會 pushReplacement 更新內容
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
