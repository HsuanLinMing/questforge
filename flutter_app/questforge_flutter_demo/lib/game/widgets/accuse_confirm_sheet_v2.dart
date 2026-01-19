import 'package:flutter/material.dart';

class AccuseConfirmSheetV2 extends StatelessWidget {
  const AccuseConfirmSheetV2({
    super.key,
    required this.selectedName,
    required this.onCancel,
    required this.onConfirm,
    this.heard,
  });

  final String selectedName;
  final String? heard;
  final VoidCallback onCancel;
  final VoidCallback onConfirm;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 44,
              height: 5,
              decoration: BoxDecoration(
                color: theme.colorScheme.outlineVariant,
                borderRadius: BorderRadius.circular(999),
              ),
            ),
            const SizedBox(height: 12),
            Text(
              '準備送出囉！',
              style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w900),
            ),
            const SizedBox(height: 10),

            if (heard != null && heard!.trim().isNotEmpty) ...[
              Align(
                alignment: Alignment.centerLeft,
                child: Text('我聽到你說：', style: theme.textTheme.labelMedium),
              ),
              const SizedBox(height: 4),
              Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  heard!.trim(),
                  style: theme.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w800),
                ),
              ),
              const SizedBox(height: 10),
            ],

            Align(
              alignment: Alignment.centerLeft,
              child: Text('你要送出這個答案嗎？', style: theme.textTheme.labelMedium),
            ),
            const SizedBox(height: 6),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceVariant,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(
                selectedName,
                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w900),
              ),
            ),

            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: onCancel,
                    child: const Text('再想想'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: FilledButton(
                    onPressed: onConfirm,
                    child: const Text('送出'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
