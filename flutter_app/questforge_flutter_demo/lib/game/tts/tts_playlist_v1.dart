class TtsPlaylistItemV1 {
  final int index; // paragraph index for highlighting
  final String role;
  final String voice;
  final String text;
  final String path; // file://...
  final String format; // mp3

  const TtsPlaylistItemV1({
    required this.index,
    required this.role,
    required this.voice,
    required this.text,
    required this.path,
    required this.format,
  });

  factory TtsPlaylistItemV1.fromMap(Map<String, dynamic> m) {
    return TtsPlaylistItemV1(
      index: (m['index'] is int) ? m['index'] as int : int.tryParse('${m['index']}') ?? 0,
      role: '${m['role'] ?? ''}',
      voice: '${m['voice'] ?? ''}',
      text: '${m['text'] ?? ''}',
      path: '${m['path'] ?? ''}',
      format: '${m['format'] ?? ''}',
    );
  }
}

class TtsPlaylistV1 {
  final String scope; // "view" | "end"
  final String viewFp;
  final String status; // ok | unavailable | empty_narration | error
  final String reason;
  final List<TtsPlaylistItemV1> items;

  const TtsPlaylistV1({
    required this.scope,
    required this.viewFp,
    required this.status,
    required this.reason,
    required this.items,
  });

  bool get playable => status == 'ok' && items.isNotEmpty;

  factory TtsPlaylistV1.fromCommandMap(Map<String, dynamic> cmd) {
    final rawItems = cmd['items'];
    final list = (rawItems is List)
        ? rawItems.whereType<Map>().map((e) => TtsPlaylistItemV1.fromMap(e.cast<String, dynamic>())).toList()
        : <TtsPlaylistItemV1>[];

    return TtsPlaylistV1(
      scope: '${cmd['scope'] ?? 'view'}',
      viewFp: '${cmd['view_fp'] ?? ''}',
      status: '${cmd['status'] ?? 'ok'}',
      reason: '${cmd['reason'] ?? ''}',
      items: list,
    );
  }
}
