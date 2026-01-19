// lib/debug/end_screen_overlay.dart
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:questforge_ui_contract/questforge_contract.dart';

/// EndScreen overlay (no Navigator usage)
/// - Uses controller-provided lockVN/pendingVN to prevent double-tap
/// - No auto-close: it stays until next step_result removes `end` from bundle
/// - ✅ Day23-D: 移除 SnackBar（debug toast 交給外層頁面/控制器）
class EndScreenOverlayV2 extends StatelessWidget {
  const EndScreenOverlayV2({
    super.key,
    required this.cmd,
    required this.lockVN,
    required this.pendingVN,
    required this.onTapAction,
    required this.onClose,
    this.showCloseButton = false,
  });

  final ShowEndScreenCommandV2 cmd;

  final ValueNotifier<bool> lockVN;
  final ValueNotifier<String?> pendingVN;

  /// ✅ 收斂：直接把 action spec 回傳給 controller
  final void Function(UiActionSpecV2 action) onTapAction;

  /// optional: allow closing overlay (you can choose to hide close button)
  final VoidCallback onClose;

  final bool showCloseButton;

  @override
  Widget build(BuildContext context) {
    // ✅ actions 空：不顯示 overlay（避免卡住）
    if (cmd.actions.isEmpty) return const SizedBox.shrink();

    return Positioned.fill(
      child: Material(
        color: Colors.black54,
        child: SafeArea(
          child: Align(
            alignment: Alignment.bottomCenter,
            child: Container(
              constraints: const BoxConstraints(maxWidth: 720),
              margin: const EdgeInsets.all(12),
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.surface,
                borderRadius: BorderRadius.circular(16),
              ),
              child: _Content(
                cmd: cmd,
                lockVN: lockVN,
                pendingVN: pendingVN,
                onTapAction: onTapAction,
                onClose: onClose,
                showCloseButton: showCloseButton,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Content extends StatelessWidget {
  const _Content({
    required this.cmd,
    required this.lockVN,
    required this.pendingVN,
    required this.onTapAction,
    required this.onClose,
    required this.showCloseButton,
  });

  final ShowEndScreenCommandV2 cmd;

  final ValueNotifier<bool> lockVN;
  final ValueNotifier<String?> pendingVN;

  final void Function(UiActionSpecV2 action) onTapAction;

  final VoidCallback onClose;
  final bool showCloseButton;

  @override
  Widget build(BuildContext context) {
    final EndContentV2 end = cmd.end;
    final ReasoningSummaryV2? reasoning = cmd.summary;
    final List<UiActionSpecV2> actions = cmd.actions;

    final title = end.title.isEmpty ? 'EndScreen' : end.title;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        // header
        Row(
          children: [
            Expanded(
              child: Text(
                title,
                style: Theme.of(context).textTheme.titleLarge,
              ),
            ),
            if (showCloseButton)
              IconButton(
                tooltip: 'Close',
                onPressed: onClose,
                icon: const Icon(Icons.close),
              ),
          ],
        ),
        const SizedBox(height: 8),

        // body (scrollable)
        Flexible(
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (end.narration.isNotEmpty) Text(end.narration),
                if (end.narration.isNotEmpty) const SizedBox(height: 12),

                if (end.lessons.isNotEmpty) ...[
                  Text('今天學到的', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 6),
                  ...end.lessons.map(
                    (e) => Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: Text('• $e'),
                    ),
                  ),
                  const SizedBox(height: 12),
                ],

                if (reasoning != null) ...[
                  Text('理由整理（v2）', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 6),
                  Text(
                    reasoning.reason.text.isNotEmpty ? reasoning.reason.text : reasoning.reason.selectedObservationIds.join('、'),
                  ),
                  const SizedBox(height: 10),
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
                  const SizedBox(height: 12),
                ],

                Text('接下來要做什麼？', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),

                // pending status（保留：顯示目前送出的 label）
                ValueListenableBuilder<bool>(
                  valueListenable: lockVN,
                  builder: (_, locked, __) {
                    if (!locked) return const SizedBox.shrink();
                    return ValueListenableBuilder<String?>(
                      valueListenable: pendingVN,
                      builder: (_, pending, __) {
                        final text = (pending == null || pending.isEmpty) ? '處理中…' : '處理中：$pending…';
                        return Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: Text(text),
                        );
                      },
                    );
                  },
                ),

                // actions
                ...actions.map((a) {
                  final label = (a.text ?? '').trim().isEmpty ? '下一步' : (a.text ?? '');

                  return Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: SizedBox(
                      width: double.infinity,
                      child: ValueListenableBuilder<bool>(
                        valueListenable: lockVN,
                        builder: (_, locked, __) {
                          return ValueListenableBuilder<String?>(
                            valueListenable: pendingVN,
                            builder: (_, pending, __) {
                              final isThisPending = locked && (pending != null) && pending == label;

                              return FilledButton(
                                onPressed: locked
                                    ? null
                                    : () {
                                        final fixed = (a.kind == null)
                                            ? UiActionSpecV2(
                                                kind: UiActionKindV2.endFlow,
                                                id: a.id,
                                                text: a.text,
                                                data: a.data,
                                              )
                                            : a;
                                        onTapAction(fixed);
                                      },
                                child: Text(isThisPending ? '$label（處理中…）' : label),
                              );
                            },
                          );
                        },
                      ),
                    ),
                  );
                }),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
