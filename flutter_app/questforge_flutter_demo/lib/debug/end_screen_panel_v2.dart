import 'package:flutter/material.dart';
import 'package:questforge_ui_contract/questforge_contract.dart';

class EndScreenPanelV2 extends StatelessWidget {
  const EndScreenPanelV2({
    super.key,
    required this.command,
    required this.kindToWire,
    required this.lockVN,
    required this.pendingVN,
    required this.onSendEndFlow,
    required this.onClose,
  });

  final ShowEndScreenCommandV2 command;

  /// enum/string -> wire string
  final String Function(Object? kind) kindToWire;

  /// 由 controller 提供
  final ValueNotifier<bool> lockVN;
  final ValueNotifier<String?> pendingVN;

  /// actionId: 用來 lock/log；kind/id/data: 真正送回 python 的 ui_action payload
  final void Function(
    String actionId,
    String kind,
    String id,
    Map<String, dynamic>? data,
  ) onSendEndFlow;

  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final end = command.end;
    final reasoning = command.summary;

    return Stack(
      children: [
        // dim background + block touches
        const ModalBarrier(dismissible: false, color: Colors.black54),

        SafeArea(
          child: Align(
            alignment: Alignment.center,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 720),
              child: Material(
                elevation: 10,
                borderRadius: BorderRadius.circular(16),
                clipBehavior: Clip.antiAlias,
                child: SizedBox(
                  height: MediaQuery.of(context).size.height * 0.85,
                  child: Column(
                    children: [
                      _Header(
                        title: end.title.isEmpty ? 'EndScreen' : end.title,
                        onClose: onClose,
                      ),
                      const Divider(height: 1),
                      Expanded(
                        child: ListView(
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

                            // pending label
                            ValueListenableBuilder<bool>(
                              valueListenable: lockVN,
                              builder: (_, locked, __) {
                                if (!locked) return const SizedBox.shrink();
                                return ValueListenableBuilder<String?>(
                                  valueListenable: pendingVN,
                                  builder: (_, pending, __) {
                                    final text = pending == null || pending.isEmpty ? '處理中…' : '處理中：$pending…';
                                    return Padding(
                                      padding: const EdgeInsets.only(bottom: 12),
                                      child: Text(text),
                                    );
                                  },
                                );
                              },
                            ),

                            ...command.actions.map((a) {
                              final wireKind = kindToWire(a.kind);
                              final id = (a.id ?? '').toString();
                              final actionId = '$wireKind/$id';
                              final data =
                                  (a.data is Map) ? Map<String, dynamic>.from(a.data as Map) : null;

                              return Padding(
                                padding: const EdgeInsets.only(bottom: 10),
                                child: ValueListenableBuilder<bool>(
                                  valueListenable: lockVN,
                                  builder: (_, locked, __) {
                                    return FilledButton(
                                      onPressed: locked
                                          ? null
                                          : () {
                                              onSendEndFlow(actionId, wireKind, id, data);
                                              ScaffoldMessenger.of(context).showSnackBar(
                                                SnackBar(content: Text('已送出 ui_action：$wireKind/$id')),
                                              );
                                            },
                                      child: Text(locked ? '${a.text}（處理中…）' : a.text),
                                    );
                                  },
                                ),
                              );
                            }),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.title, required this.onClose});

  final String title;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 56,
      child: Row(
        children: [
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              title,
              style: Theme.of(context).textTheme.titleMedium,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          IconButton(
            onPressed: onClose,
            icon: const Icon(Icons.close),
            tooltip: 'Close',
          ),
          const SizedBox(width: 4),
        ],
      ),
    );
  }
}
