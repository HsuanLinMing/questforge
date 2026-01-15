// lib/game/widgets/choice_card_v2.dart
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

class ChoiceCardV2 extends StatelessWidget {
  const ChoiceCardV2({
    super.key,
    required this.index,
    required this.text,
    required this.enabled,
    required this.highlighted,
    required this.pending,
    required this.onTap,
  });

  final int index;
  final String text;
  final bool enabled;
  final bool highlighted;
  final bool pending;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;

    final bg = highlighted ? cs.primaryContainer : cs.surface;
    final border = highlighted
        ? Border.all(color: cs.primary, width: 1.4)
        : Border.all(color: cs.outlineVariant);

    return AnimatedOpacity(
      duration: const Duration(milliseconds: 120),
      opacity: enabled ? 1.0 : 0.55,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        curve: Curves.easeOut,
        decoration: BoxDecoration(
          color: bg,
          border: border,
          borderRadius: BorderRadius.circular(16),
          boxShadow: kElevationToShadow[1],
        ),
        child: InkWell(
          onTap: enabled ? onTap : null,
          borderRadius: BorderRadius.circular(16),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('$index.', style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    text,
                    style: theme.textTheme.titleMedium?.copyWith(height: 1.35),
                  ),
                ),
                const SizedBox(width: 10),
                if (pending)
                  SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(
                      strokeWidth: 2.4,
                      valueColor: AlwaysStoppedAnimation<Color>(cs.primary),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
