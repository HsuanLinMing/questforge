import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:questforge_flutter_demo/nav.dart';
import 'package:questforge_flutter_demo/pages/bridge_debug_page.dart';
import 'package:questforge_ui_contract/questforge_contract.dart';
import 'package:flutter/services.dart';

void main() {
  runApp(const QuestForgeDemoApp());
}

class QuestForgeDemoApp extends StatelessWidget {
  const QuestForgeDemoApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      navigatorKey: qfNavKey,
      title: 'QuestForge Demo',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(useMaterial3: true),
      home: const BridgeDebugPage(),
    );
  }
}

class DemoHomePage extends StatefulWidget {
  const DemoHomePage({super.key});

  @override
  State<DemoHomePage> createState() => _DemoHomePageState();
}

class _DemoHomePageState extends State<DemoHomePage> {
  final _controller = TextEditingController(text: _sampleShowEndScreenJson);
  String _error = '';

  void _openEndScreenFromJson() {
    setState(() => _error = '');

    try {
      final obj = jsonDecode(_controller.text);
      final cmd = SessionCommand.fromJson(obj);

      if (cmd is! ShowEndScreenCommand) {
        setState(() => _error = '這份 JSON 不是 show_end_screen（type=${cmd.type.value}）');
        return;
      }

      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => EndScreenPage(command: cmd),
        ),
      );
    } catch (e) {
      setState(() => _error = 'JSON 解析失敗：$e');
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('QuestForge Day20-C Demo')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            const Text(
              '貼上 bridge 回來的 show_end_screen JSON，按「預覽 EndScreen」即可。\n'
              '（Day20-C：只做 show_end_screen UI）',
            ),
            const SizedBox(height: 12),
            Expanded(
              child: TextField(
                controller: _controller,
                maxLines: null,
                expands: true,
                decoration: InputDecoration(
                  border: const OutlineInputBorder(),
                  labelText: 'show_end_screen JSON',
                  errorText: _error.isEmpty ? null : _error,
                ),
              ),
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: _openEndScreenFromJson,
                child: const Text('預覽 EndScreen'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Day20-C：只需要 show_end_screen 的第一個 UI。
class EndScreenPage extends StatelessWidget {
  const EndScreenPage({super.key, required this.command});

  final ShowEndScreenCommand command;

  @override
  Widget build(BuildContext context) {
    final meta = command.meta;

    return Scaffold(
      appBar: AppBar(title: Text(command.title.isNotEmpty ? command.title : 'EndScreen')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _SectionTitle('結尾內容'),
          Text(command.narration),
          const SizedBox(height: 16),
          if (command.lesson.isNotEmpty) ...[
            _SectionTitle('今天學到的'),
            ...command.lesson.take(6).map((e) => Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Text('• $e'),
                )),
          ],
          const SizedBox(height: 16),
          _SectionTitle('理由整理'),
          Text(meta.reasonSummary.isNotEmpty ? meta.reasonSummary : '（沒有提供）'),
          const SizedBox(height: 16),
          _SectionTitle('回顧卡片'),
          _Kv('案件', meta.caseTitle),
          _Kv('回合', '${meta.turn}'),
          _Kv('你偏向', meta.accused.isEmpty ? '（未填）' : meta.accused),
          if (meta.selectedObservations.isNotEmpty) ...[
            const SizedBox(height: 8),
            const Text('你選的觀察：', style: TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: 6),
            ...meta.selectedObservations.take(6).map((x) => Text('• $x')),
          ],
          const SizedBox(height: 8),
          _Kv('成熟度', '${meta.level}  ${meta.threshold > 0 ? "${meta.score}/${meta.threshold}" : ""}'.trim()),
          if (meta.matchedEvidence.isNotEmpty) _Kv('有用到的線索', meta.matchedEvidence.take(6).join('、')),
          if (meta.missingKeyEvidence.isNotEmpty) _Kv('可以再留意', meta.missingKeyEvidence.take(6).join('、')),
          const SizedBox(height: 24),
          _SectionTitle('接下來要做什麼？'),
          const SizedBox(height: 8),
          ...command.options.map((opt) {
            return Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: FilledButton.tonal(
                onPressed: () async {
                  final payload = <String, dynamic>{
                    'type': 'flow',
                    'action': opt.id, // go_epilogue / restart_case / switch_case / quit
                  };
                  final pretty = const JsonEncoder.withIndent('  ').convert(payload);

                  await showDialog<void>(
                    context: context,
                    builder: (ctx) => AlertDialog(
                      title: const Text('end_flow payload'),
                      content: SelectableText(pretty),
                      actions: [
                        TextButton(
                          onPressed: () async {
                            await Clipboard.setData(ClipboardData(text: pretty));
                            if (!ctx.mounted) return;

                            Navigator.of(ctx).pop();

                            ScaffoldMessenger.of(ctx).showSnackBar(
                              const SnackBar(content: Text('已複製到剪貼簿')),
                            );
                          },
                          child: const Text('複製'),
                        ),
                        TextButton(
                          onPressed: () => Navigator.of(ctx).pop(),
                          child: const Text('關閉'),
                        ),
                      ],
                    ),
                  );
                },
                child: Text(opt.text),
              ),
            );
          }),
        ],
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Text(text, style: Theme.of(context).textTheme.titleMedium),
      );
}

class _Kv extends StatelessWidget {
  const _Kv(this.k, this.v);
  final String k;
  final String v;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 72, child: Text(k, style: const TextStyle(fontWeight: FontWeight.w600))),
          Expanded(child: Text(v.isEmpty ? '—' : v)),
        ],
      ),
    );
  }
}

/// 你可以把這段換成你 python bridge 實際輸出的 show_end_screen payload。
const String _sampleShowEndScreenJson = r'''
{
  "type": "show_end_screen",
  "node_id": "ending_result",
  "tag": "ending_result",
  "title": "老師帶我們一起確認",
  "narration": "老師微笑著說：謝謝你們願意先整理觀察，而不是急著說名字。",
  "lesson": ["先說看到的，不急著下結論", "覺得不確定時，找老師一起確認是很勇敢的"],
  "options": [{"id":"go_epilogue","text":"進入尾聲"}],
  "meta": {
    "version": "reasoning_contract_v1",
    "case_title": "校園案：運動會貼紙日",
    "node_id": "ending_result",
    "tag": "ending_result",
    "turn": 6,
    "accused": "dongdong",
    "reason_mode": "choice",
    "reason_ids": ["dongdong_hug_tight"],
    "selected_observations": ["東東一直把運動護照抱很緊、坐不住"],
    "reason_text": "",
    "reason_summary": "東東一直把運動護照抱很緊、坐不住",
    "clues_preview": ["透明背紙", "桌上有被拉過的痕跡"],
    "level": "ok",
    "score": 2,
    "threshold": 3,
    "engine_message": "你有在用觀察，但還差一個關鍵線索。",
    "matched_evidence": ["透明背紙"],
    "missing_key_evidence": ["膠帶"]
  }
}
''';
