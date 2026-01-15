// lib/debug/debug_panel_v2.dart
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:questforge_flutter_demo/bridge/bridge_controller_v2.dart';


class DebugPanelV2 extends StatelessWidget {
  const DebugPanelV2({
    super.key,
    required this.controller,
  });

  final BridgeControllerV2 controller;

  String _clip(String s, [int n = 4000]) => s.length <= n ? s : '${s.substring(0, n)}\n...(${s.length} chars)';

  @override
  Widget build(BuildContext context) {
    if (!kDebugMode) return const SizedBox.shrink();

    return Drawer(
      child: SafeArea(
        child: ValueListenableBuilder<BridgeUiStateV2>(
          valueListenable: controller.stateVN,
          builder: (context, state, _) {
            return ListView(
              padding: const EdgeInsets.all(12),
              children: [
                Text('Debug Panel', style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: 12),

                // quick status
                Text('node_id: ${state.snapshot.nodeId}'),
                Text('is_over: ${state.snapshot.isOver}'),
                Text('end_lock: ${state.snapshot.endActionLocked}'),
                Text('pending: ${state.snapshot.pendingEndActionId ?? "—"}'),
                const Divider(height: 24),

                Text('Commands (${state.commands.length})', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                ...state.commands.map((c) => ListTile(
                      dense: true,
                      title: Text(c.type),
                      subtitle: Text(const JsonEncoder.withIndent('  ').convert(c.toJson())),
                    )),

                const Divider(height: 24),
                Text('Snapshot', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                SelectableText(const JsonEncoder.withIndent('  ').convert(state.snapshot.toJson())),

                const Divider(height: 24),
                Text('Last raw', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                SelectableText(state.lastRaw == null ? '—' : _clip(jsonEncode(state.lastRaw))),
              ],
            );
          },
        ),
      ),
    );
  }
}
