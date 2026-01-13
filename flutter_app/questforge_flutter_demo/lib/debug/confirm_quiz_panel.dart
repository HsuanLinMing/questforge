import 'package:flutter/material.dart';
import 'package:questforge_ui_contract/questforge_contract.dart';

class ConfirmQuizPanel extends StatefulWidget {
  const ConfirmQuizPanel({
    super.key,
    required this.command,
    required this.onSubmit,
    this.onClose,
  });

  final ConfirmQuizCommandV2 command;

  /// 最小版：把 quiz 原樣回送（或回送選到的索引/鍵）
  final void Function(List<Object?> answers) onSubmit;

  final VoidCallback? onClose;

  @override
  State<ConfirmQuizPanel> createState() => _ConfirmQuizPanelState();
}

class _ConfirmQuizPanelState extends State<ConfirmQuizPanel> {
  /// 每題選到的 index（-1 = 未選）
  late final List<int> _picked;

  @override
  void initState() {
    super.initState();
    _picked = List<int>.filled(_quizList.length, -1, growable: false);
  }

  List<Map<String, dynamic>> get _quizList {
    final raw = widget.command.quiz;
    final out = <Map<String, dynamic>>[];
    for (final x in raw) {
      if (x is Map) {
        out.add(x.map((k, v) => MapEntry(k.toString(), v)));
      }
    }
    return out;
  }

  List<String> _labelsOf(Map<String, dynamic> q) {
    final v = q['labels'];
    if (v is List) {
      return v.map((e) => (e ?? '').toString()).toList(growable: false);
    }
    // fallback：沒有 labels 就用 options
    final opt = q['options'];
    if (opt is List) {
      return opt.map((e) => (e ?? '').toString()).toList(growable: false);
    }
    return const [];
  }

  bool get _canSubmit {
    // 最小版：允許不全選也送（你想強制全選可改）
    return true;
  }

  @override
  Widget build(BuildContext context) {
    final quizzes = _quizList;

    return Material(
      color: Colors.black54,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text(
                    '小回顧（可選）',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    '選一個就好（最小版示範）',
                    style: TextStyle(fontSize: 13),
                  ),
                  const SizedBox(height: 12),

                  ...List.generate(quizzes.length, (qi) {
                    final q = quizzes[qi];
                    final qText = (q['q'] ?? '').toString();
                    final labels = _labelsOf(q);

                    return Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Text(qText, style: const TextStyle(fontWeight: FontWeight.w600)),
                          const SizedBox(height: 6),
                          ...List.generate(labels.length, (i) {
                            return RadioListTile<int>(
                              value: i,
                              groupValue: _picked[qi],
                              dense: true,
                              title: Text(labels[i]),
                              onChanged: (v) {
                                setState(() {
                                  _picked[qi] = v ?? -1;
                                });
                              },
                            );
                          }),
                        ],
                      ),
                    );
                  }),

                  const SizedBox(height: 8),

                  Row(
                    children: [
                      if (widget.onClose != null)
                        TextButton(
                          onPressed: widget.onClose,
                          child: const Text('稍後再說'),
                        ),
                      const Spacer(),
                      ElevatedButton(
                        onPressed: _canSubmit
                            ? () {
                                // answers: 每題回傳選到的 option index（-1 表示沒選）
                                final answers = _picked.map<Object?>((e) => e).toList(growable: false);
                                widget.onSubmit(answers);
                              }
                            : null,
                        child: const Text('送出'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
