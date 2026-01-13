import 'package:flutter/material.dart';
import 'package:questforge_ui_contract/questforge_contract.dart';

class AskReasonPanel extends StatefulWidget {
  const AskReasonPanel({
    super.key,
    required this.command,
    required this.onSubmit,
    this.onClose,
  });

  final AskReasonCommandV2 command;
  final void Function(List<String> reasonIds, String reasonText) onSubmit;
  final VoidCallback? onClose;

  @override
  State<AskReasonPanel> createState() => _AskReasonPanelState();
}

class _AskReasonPanelState extends State<AskReasonPanel> {
  final _text = TextEditingController();
  final _selected = <String>{};

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cmd = widget.command;

    return Material(
      color: Colors.black54,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(cmd.title, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 8),
                  Text(cmd.hint, style: const TextStyle(fontSize: 13)),
                  const SizedBox(height: 12),

                  // options (multi-select)
                  ...cmd.options.map((o) {
                    final checked = _selected.contains(o.id);
                    return CheckboxListTile(
                      value: checked,
                      dense: true,
                      title: Text(o.text),
                      controlAffinity: ListTileControlAffinity.leading,
                      onChanged: (v) {
                        setState(() {
                          if (v == true) {
                            _selected.add(o.id);
                          } else {
                            _selected.remove(o.id);
                          }
                        });
                      },
                    );
                  }),

                  const SizedBox(height: 8),

                  // mode == "text" 也可讓孩子補充一句（最小版都給）
                  TextField(
                    controller: _text,
                    maxLength: cmd.maxLen,
                    decoration: const InputDecoration(
                      labelText: '補充一句（可不填）',
                      border: OutlineInputBorder(),
                    ),
                  ),

                  const SizedBox(height: 12),

                  Row(
                    children: [
                      if (widget.onClose != null)
                        TextButton(
                          onPressed: widget.onClose,
                          child: const Text('取消'),
                        ),
                      const Spacer(),
                      ElevatedButton(
                        onPressed: () {
                          widget.onSubmit(_selected.toList(growable: false), _text.text.trim());
                        },
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
