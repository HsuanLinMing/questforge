// lib/game/widgets/story_card_v2.dart
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

@immutable
class StoryParagraph {
  const StoryParagraph(this.text, {this.index = 0});
  final String text;
  final int index;
}

List<StoryParagraph> parseParagraphs(String narration) {
  final parts = narration
      .split(RegExp(r'\n\s*\n'))
      .map((e) => e.trim())
      .where((e) => e.isNotEmpty)
      .toList();

  return [
    for (int i = 0; i < parts.length; i++) StoryParagraph(parts[i], index: i),
  ];
}

/// Story Card (scroll + fade + paragraph playback controls)
class StoryCardV2 extends StatefulWidget {
  const StoryCardV2({
    super.key,
    required this.chapterLabel,
    required this.paragraphs,
    required this.activeIndex,
    required this.isPlaying,
    required this.ttsReady,
    required this.onTogglePlay,
    required this.onPrev,
    required this.onNext,
    required this.onTapParagraph,
    required this.rebuildEpoch,
    required this.scrollEnabled,

    /// ✅ 右上角 menu（之後功能都放這裡）
    required this.onOpenMenu,

    /// ✅ 顯示目前語速（小字）
    required this.rate,
  });

  final String chapterLabel;
  final List<StoryParagraph> paragraphs;

  /// macOS resume workaround：外部 epoch 改變時重建 ScrollController
  final int rebuildEpoch;

  final int activeIndex;
  final bool isPlaying;
  final bool ttsReady;

  final VoidCallback? onTogglePlay;
  final VoidCallback? onPrev;
  final VoidCallback? onNext;

  final ValueChanged<int>? onTapParagraph;

  /// phase 控制可不可以滑
  final bool scrollEnabled;

  /// ✅ 右上角 menu
  final VoidCallback? onOpenMenu;

  /// ✅ 目前語速顯示（例如 0.45）
  final double rate;

  @override
  State<StoryCardV2> createState() => StoryCardV2State();
}

class StoryCardV2State extends State<StoryCardV2> {
  late ScrollController _sc;
  bool _showBottomFade = false;

  List<GlobalKey> _paraKeys = const <GlobalKey>[];

  @override
  void initState() {
    super.initState();
    _sc = ScrollController();
    _sc.addListener(_recalcFade);

    _paraKeys = List.generate(widget.paragraphs.length, (_) => GlobalKey());
    WidgetsBinding.instance.addPostFrameCallback((_) => _recalcFade());
  }

  @override
  void didUpdateWidget(covariant StoryCardV2 oldWidget) {
    super.didUpdateWidget(oldWidget);

    // ✅ resume 回來：強制重建 ScrollController，避免 macOS gesture/scroll 卡死殘留
    if (oldWidget.rebuildEpoch != widget.rebuildEpoch) {
      _sc.removeListener(_recalcFade);
      _sc.dispose();
      _sc = ScrollController();
      _sc.addListener(_recalcFade);
      _showBottomFade = false;

      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        _recalcFade();
      });
    }

    // 段落數變了 -> keys 重建
    if (oldWidget.paragraphs.length != widget.paragraphs.length) {
      _paraKeys = List.generate(widget.paragraphs.length, (_) => GlobalKey());
      WidgetsBinding.instance.addPostFrameCallback((_) => _recalcFade());
    }

    // 內容換了 -> 回頂
    if (!_sameParagraphs(oldWidget.paragraphs, widget.paragraphs)) {
      if (_sc.hasClients) _sc.jumpTo(0);
      WidgetsBinding.instance.addPostFrameCallback((_) => _recalcFade());
    }
  }

  bool _sameParagraphs(List<StoryParagraph> a, List<StoryParagraph> b) {
    if (a.length != b.length) return false;
    for (int i = 0; i < a.length; i++) {
      if (a[i].text != b[i].text) return false;
    }
    return true;
  }

  @override
  void dispose() {
    _sc.removeListener(_recalcFade);
    _sc.dispose();
    super.dispose();
  }

  void _recalcFade() {
    if (!mounted) return;
    if (!_sc.hasClients) return;

    final max = _sc.position.maxScrollExtent;
    final off = _sc.offset;

    final shouldShow = max > 4 && off < (max - 2);
    if (shouldShow != _showBottomFade) {
      setState(() => _showBottomFade = shouldShow);
    }
  }

  /// 給外部（GamePage）呼叫，做「段落定位」
  void scrollToParagraph(int index) {
    if (widget.paragraphs.isEmpty) return;
    if (index < 0 || index >= widget.paragraphs.length) return;

    if (_paraKeys.isEmpty || _paraKeys.length != widget.paragraphs.length) {
      _paraKeys = List.generate(widget.paragraphs.length, (_) => GlobalKey());
    }

    final key = _paraKeys[index];
    final ctx = key.currentContext;
    if (ctx == null) return;

    Scrollable.ensureVisible(
      ctx,
      duration: const Duration(milliseconds: 220),
      curve: Curves.easeOut,
      alignment: 0.18,
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;

    if (_paraKeys.isEmpty || _paraKeys.length != widget.paragraphs.length) {
      _paraKeys = List.generate(widget.paragraphs.length, (_) => GlobalKey());
    }

    final total = widget.paragraphs.length;
    final active = total == 0 ? 0 : widget.activeIndex.clamp(0, total - 1);

    final scrollPhysics = widget.scrollEnabled ? const BouncingScrollPhysics() : const NeverScrollableScrollPhysics();
    final rateLabel = widget.rate.toStringAsFixed(2);

    return Card(
      elevation: 0,
      surfaceTintColor: cs.surfaceTint,
      color: cs.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: BorderSide(color: cs.outlineVariant),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                ChapterPill(label: widget.chapterLabel),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    '故事',
                    style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                  ),
                ),

                if (widget.ttsReady)
                  Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: Text(
                      '${rateLabel}x',
                      style: theme.textTheme.labelSmall?.copyWith(color: cs.outline),
                    ),
                  ),

                IconButton(
                  tooltip: '功能選單',
                  onPressed: widget.onOpenMenu,
                  icon: const Icon(Icons.more_vert),
                ),

                PlaybackControlsCompact(
                  isPlaying: widget.isPlaying,
                  ttsReady: widget.ttsReady,
                  onPrev: widget.onPrev,
                  onToggle: widget.onTogglePlay,
                  onNext: widget.onNext,
                ),
              ],
            ),
            const SizedBox(height: 8),
            if (total > 0) ...[
              Text(
                '段落 ${active + 1} / $total',
                style: theme.textTheme.labelMedium?.copyWith(color: cs.outline),
              ),
              const SizedBox(height: 10),
            ],
            LayoutBuilder(
              builder: (context, constraints) {
                final maxH = _maxStoryHeight(context);

                return ConstrainedBox(
                  constraints: BoxConstraints(maxHeight: maxH),
                  child: Stack(
                    children: [
                      Scrollbar(
                        controller: _sc,
                        thumbVisibility: false,
                        child: SingleChildScrollView(
                          controller: _sc,
                          physics: scrollPhysics,
                          child: DefaultTextStyle.merge(
                            style: const TextStyle(height: 1.65),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                for (int i = 0; i < widget.paragraphs.length; i++) ...[
                                  ParagraphTile(
                                    key: _paraKeys[i],
                                    index: i,
                                    text: widget.paragraphs[i].text,
                                    active: i == active,
                                    enabled: widget.onTapParagraph != null && widget.scrollEnabled,
                                    onTap: (widget.onTapParagraph == null || !widget.scrollEnabled) ? null : () => widget.onTapParagraph!(i),
                                  ),
                                  const SizedBox(height: 12),
                                ],
                                const SizedBox(height: 2),
                              ],
                            ),
                          ),
                        ),
                      ),
                      if (_showBottomFade)
                        Positioned(
                          left: 0,
                          right: 0,
                          bottom: 0,
                          child: IgnorePointer(
                            child: Container(
                              height: 40,
                              decoration: BoxDecoration(
                                gradient: LinearGradient(
                                  begin: Alignment.topCenter,
                                  end: Alignment.bottomCenter,
                                  colors: [
                                    cs.surface.withOpacity(0.0),
                                    cs.surface.withOpacity(1.0),
                                  ],
                                ),
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                );
              },
            ),
          ],
        ),
      ),
    );
  }

  double _maxStoryHeight(BuildContext context) {
    final h = MediaQuery.of(context).size.height;
    return (h * 0.46).clamp(220.0, 420.0);
  }
}

class ChapterPill extends StatelessWidget {
  const ChapterPill({super.key, required this.label});
  final String label;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: cs.primaryContainer,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: cs.primary.withOpacity(0.25)),
      ),
      child: Text(
        label,
        style: theme.textTheme.labelMedium?.copyWith(
          color: cs.onPrimaryContainer,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

/// ✅ 只留 3 顆：上一段 / 播放暫停 / 下一段
class PlaybackControlsCompact extends StatelessWidget {
  const PlaybackControlsCompact({
    super.key,
    required this.isPlaying,
    required this.ttsReady,
    required this.onPrev,
    required this.onToggle,
    required this.onNext,
  });

  final bool isPlaying;
  final bool ttsReady;
  final VoidCallback? onPrev;
  final VoidCallback? onToggle;
  final VoidCallback? onNext;

  @override
  Widget build(BuildContext context) {
    final disabled = !ttsReady;

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        IconButton(
          tooltip: disabled ? 'TTS 初始化中' : '上一段',
          onPressed: disabled ? null : onPrev,
          icon: const Icon(Icons.skip_previous),
        ),
        IconButton(
          tooltip: disabled ? 'TTS 初始化中' : (isPlaying ? '暫停' : '播放'),
          onPressed: disabled ? null : onToggle,
          icon: Icon(isPlaying ? Icons.pause_circle_filled : Icons.play_circle_fill),
        ),
        IconButton(
          tooltip: disabled ? 'TTS 初始化中' : '下一段',
          onPressed: disabled ? null : onNext,
          icon: const Icon(Icons.skip_next),
        ),
      ],
    );
  }
}

class ParagraphTile extends StatelessWidget {
  const ParagraphTile({
    super.key,
    required this.index,
    required this.text,
    required this.active,
    required this.enabled,
    required this.onTap,
  });

  final int index;
  final String text;
  final bool active;
  final bool enabled;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;

    final bg = active ? cs.secondaryContainer : cs.surface;
    final border = active ? Border.all(color: cs.secondary, width: 1.2) : Border.all(color: cs.outlineVariant);

    return InkWell(
      onTap: enabled ? onTap : null,
      borderRadius: BorderRadius.circular(14),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        curve: Curves.easeOut,
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
        decoration: BoxDecoration(
          color: bg,
          border: border,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 26,
              height: 26,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: active ? cs.secondary : cs.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                '${index + 1}',
                style: theme.textTheme.labelMedium?.copyWith(
                  color: active ? cs.onSecondary : cs.onSurfaceVariant,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: SelectableText(
                text,
                selectionControls: materialTextSelectionControls,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
