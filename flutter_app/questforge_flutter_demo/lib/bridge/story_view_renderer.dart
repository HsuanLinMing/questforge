// lib/dev/bridge/story_view_renderer.dart
import 'package:flutter/material.dart';
import 'package:questforge_ui_contract/questforge_contract.dart';

class StoryViewRenderer extends StatelessWidget {
  const StoryViewRenderer({
    super.key,
    required this.view,
    required this.onChoose,
    required this.choicesEnabled,
  });

  final NodeView view;
  final ValueChanged<int> onChoose;
  final bool choicesEnabled;

  @override
  Widget build(BuildContext context) {
    final choices = view.choices;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if ((view.title ?? '').isNotEmpty) ...[
          Text(
            view.title ?? '',
            style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 12),
        ],
        if ((view.narration ?? '').isNotEmpty) ...[
          Text(
            view.narration ?? '',
            style: const TextStyle(fontSize: 16, height: 1.4),
          ),
          const SizedBox(height: 18),
        ],
        ...List.generate(choices.length, (i) {
          final c = choices[i];
          final label = c.text ?? '';
          return Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: ElevatedButton(
              onPressed: choicesEnabled ? () => onChoose(i) : null,
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: Text(label, style: const TextStyle(fontSize: 16)),
                ),
              ),
            ),
          );
        }),
      ],
    );
  }
}
