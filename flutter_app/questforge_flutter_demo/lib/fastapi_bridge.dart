// lib/fastapi_bridge.dart
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:questforge_ui_contract/questforge_contract.dart';

/// ----------------------------
/// Step Response (對齊後端 StepResponse)
/// ----------------------------
/// {
///   "session_id": "...",
///   "bundle": { "view": {...}, "ask": {...}?, "quiz": {...}?, "end": {...}? },
///   "events": ["..."],
///   "is_over": false
/// }
class GameStepResp {
  GameStepResp({
    required this.sessionId,
    required this.bundle,
    required this.events,
    required this.isOver,
  });

  final String sessionId;
  final Map<String, dynamic> bundle;
  final List<String> events;
  final bool isOver;

  factory GameStepResp.fromJson(Map<String, dynamic> json) {
    return GameStepResp(
      sessionId: (json['session_id'] ?? '').toString(),
      bundle: (json['bundle'] as Map?)?.cast<String, dynamic>() ??
          <String, dynamic>{},
      events: (json['events'] as List?)?.map((e) => e.toString()).toList() ??
          <String>[],
      isOver: (json['is_over'] as bool?) ?? false,
    );
  }
}

/// start 需要額外把 session_id 存起來；其餘 API 也會回同一個 session_id
class GameStartResp extends GameStepResp {
  GameStartResp({
    required super.sessionId,
    required super.bundle,
    required super.events,
    required super.isOver,
  });

  factory GameStartResp.fromJson(Map<String, dynamic> json) {
    final base = GameStepResp.fromJson(json);
    return GameStartResp(
      sessionId: base.sessionId,
      bundle: base.bundle,
      events: base.events,
      isOver: base.isOver,
    );
  }
}

class InitializeStoriesResp {
  InitializeStoriesResp({
    required this.hasAiStories,
    required this.sampleStories,
    this.skipped,
    this.reason,
    this.queued,
  });
  final bool hasAiStories;
  final List<Map<String, dynamic>> sampleStories;
  final bool? skipped;
  final String? reason;
  final int? queued;

  factory InitializeStoriesResp.fromJson(Map<String, dynamic> json) {
    return InitializeStoriesResp(
      hasAiStories: (json['has_ai_stories'] as bool?) ?? false,
      sampleStories:
          (json['sample_stories'] as List?)?.cast<Map<String, dynamic>>() ??
              <Map<String, dynamic>>[],
      skipped: json['skipped'] as bool?,
      reason: json['reason']?.toString(),
      queued: json['queued'] as int?,
    );
  }
}

class PoolStatus {
  final int readyCount;
  final int generatingCount;
  final int ttsReadyCount;
  final int target;

  PoolStatus({
    required this.readyCount,
    required this.generatingCount,
    required this.ttsReadyCount,
    required this.target,
  });

  factory PoolStatus.fromJson(Map<String, dynamic> j) => PoolStatus(
        readyCount: (j['ready_count'] ?? 0) as int,
        generatingCount: (j['generating_count'] ?? 0) as int,
        ttsReadyCount: (j['tts_ready_count'] ?? 0) as int,
        target: (j['target'] ?? 2) as int,
      );
}

class ActionStatusResp {
  ActionStatusResp({
    required this.status,
    required this.message,
  });
  final String status;
  final String message;

  factory ActionStatusResp.fromJson(Map<String, dynamic> json) {
    return ActionStatusResp(
      status: (json['status'] ?? '').toString(),
      message: (json['message'] ?? '').toString(),
    );
  }
}

class TtsStatus {
  final bool ready;
  final int readyCount;
  final List<String> paths;
  final List<int> missing;

  TtsStatus(
      {required this.ready,
      required this.readyCount,
      required this.paths,
      required this.missing});

  factory TtsStatus.fromJson(Map<String, dynamic> j) => TtsStatus(
        ready: j['ready'] == true,
        readyCount: (j['ready_count'] ?? 0) as int,
        paths: (j['paths'] as List? ?? []).cast<String>(),
        missing: (j['missing'] as List? ?? []).map((e) => e as int).toList(),
      );
}

/// ----------------------------
/// Errors
/// ----------------------------
class ApiException implements Exception {
  ApiException(this.message, {this.statusCode, this.body});

  final String message;
  final int? statusCode;
  final String? body;

  @override
  String toString() {
    final sc = statusCode == null ? '' : ' ($statusCode)';
    final b = (body == null || body!.isEmpty) ? '' : ' body=$body';
    return 'ApiException$sc: $message$b';
  }
}

/// ----------------------------
/// Bridge
/// ----------------------------
class FastApiBridge {
  FastApiBridge({
    required String baseUrl,
    http.Client? client,
  })  : baseUrl = baseUrl.endsWith('/')
            ? baseUrl.substring(0, baseUrl.length - 1)
            : baseUrl,
        _client = client ?? http.Client();

  final String baseUrl;
  final http.Client _client;

  static const _kSessionIdKey = 'qf_session_id';

  Uri _u(String path) => Uri.parse('$baseUrl$path');

  Future<String?> loadSessionId() async {
    final sp = await SharedPreferences.getInstance();
    final sid = sp.getString(_kSessionIdKey);
    return (sid == null || sid.isEmpty) ? null : sid;
  }

  Future<void> saveSessionId(String sid) async {
    final sp = await SharedPreferences.getInstance();
    await sp.setString(_kSessionIdKey, sid);
  }

  Future<void> clearSessionId() async {
    final sp = await SharedPreferences.getInstance();
    await sp.remove(_kSessionIdKey);
  }

  String _tryParseDetail(String body) {
    try {
      final j = jsonDecode(body);
      if (j is Map && j['detail'] != null) return j['detail'].toString();
    } catch (_) {}
    return '';
  }

  Future<Map<String, dynamic>> _postJson(
    String path, {
    Map<String, dynamic>? body,
    bool clearSidOnNotFound = true,
  }) async {
    final resp = await _client.post(
      _u(path),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode(body ?? const <String, dynamic>{}),
    );

    // 後端常見：404 {"detail":"session_not_found"}
    if (resp.statusCode == 404) {
      final detail = _tryParseDetail(resp.body);
      if (clearSidOnNotFound && detail == 'session_not_found') {
        await clearSessionId();
        throw ApiException(
          'session_not_found (cleared local session_id)',
          statusCode: 404,
          body: resp.body,
        );
      }
      throw ApiException('not found', statusCode: 404, body: resp.body);
    }

    if (resp.statusCode != 200) {
      throw ApiException('request failed',
          statusCode: resp.statusCode, body: resp.body);
    }

    try {
      final json = jsonDecode(resp.body);
      if (json is Map<String, dynamic>) return json;
      if (json is Map) return json.cast<String, dynamic>();
      throw ApiException('invalid json (not a map)',
          statusCode: resp.statusCode, body: resp.body);
    } catch (e) {
      throw ApiException('invalid json decode: $e',
          statusCode: resp.statusCode, body: resp.body);
    }
  }

  Future<Map<String, dynamic>> _getJson(String path) async {
    final resp = await _client.get(_u(path));
    if (resp.statusCode != 200) {
      throw ApiException('request failed',
          statusCode: resp.statusCode, body: resp.body);
    }
    try {
      final json = jsonDecode(resp.body);
      if (json is Map<String, dynamic>) return json;
      if (json is Map) return json.cast<String, dynamic>();
      throw ApiException('invalid json (not a map)',
          statusCode: resp.statusCode, body: resp.body);
    } catch (e) {
      throw ApiException('invalid json decode: $e',
          statusCode: resp.statusCode, body: resp.body);
    }
  }

  // ----------------------------
  // APIs (全部回 GameStepResp)
  // ----------------------------

  Future<InitializeStoriesResp> initializeStories() async {
    final json = await _postJson(
      '/v1/game/initialize_stories',
      clearSidOnNotFound: false,
    );
    return InitializeStoriesResp.fromJson(json);
  }

  Future<PoolStatus> fetchPoolStatus() async {
    final json = await _getJson('/v1/game/pool_status');
    return PoolStatus.fromJson(json);
  }

  Future<TtsStatus> fetchTtsStatus(
      {required String viewFp, required int count}) async {
    final sid = await loadSessionId();
    final json = await _getJson(
        '/v1/game/tts_status?view_fp=$viewFp&count=$count${sid != null ? '&session_id=$sid' : ''}');
    return TtsStatus.fromJson(json);
  }

  /// ✅ 查詢目前 view 的 TTS playlist 進度（避免音檔還在生成時直接 skip）
  /// 回傳後端的 command（tts_playlist_v1）或 null。
  Future<Map<String, dynamic>?> fetchTtsStatusCmd() async {
    final sid = await loadSessionId();
    if (sid == null || sid.isEmpty) return null;

    final json = await _getJson('/v1/game/tts_status?session_id=$sid');
    final cmd = json['command'];
    if (cmd is Map<String, dynamic>) return cmd;
    if (cmd is Map) return cmd.cast<String, dynamic>();
    return null;
  }

  Future<void> ensurePoolFilledIfNeeded() async {
    try {
      final s = await fetchPoolStatus();
      final total = s.readyCount + s.generatingCount;
      if (total < s.target) {
        await initializeStoriesOnce(force: true);
      }
    } catch (e) {
      // Ignore if it fails
      print('ensurePoolFilledIfNeeded failed: $e');
    }
  }

  // --------------------------------------------------------------------------
  // initializeStories guard (avoid duplicate background generation)
  // --------------------------------------------------------------------------
  static Future<InitializeStoriesResp>? _initStoriesInFlight;
  static InitializeStoriesResp? _initStoriesCache;

  /// ✅ Call initialize_stories only once per app run (unless force=true).
  /// - If a request is already in-flight, awaits the same future.
  /// - If it has succeeded before, returns cached result.
  Future<InitializeStoriesResp> initializeStoriesOnce(
      {bool force = false}) async {
    if (!force && _initStoriesCache != null) return _initStoriesCache!;
    final inflight = _initStoriesInFlight;
    if (!force && inflight != null) return await inflight;

    final fut = initializeStories();
    _initStoriesInFlight = fut;
    try {
      final resp = await fut;
      _initStoriesCache = resp;
      return resp;
    } finally {
      // only clear if it's still the same future
      if (identical(_initStoriesInFlight, fut)) {
        _initStoriesInFlight = null;
      }
    }
  }

  Future<ActionStatusResp> generateAiStory() async {
    final json = await _postJson(
      '/v1/game/generate_ai_story',
      clearSidOnNotFound: false,
    );
    return ActionStatusResp.fromJson(json);
  }

  Future<ActionStatusResp> cleanupAiStory(String storyId) async {
    final json = await _postJson(
      '/v1/game/cleanup_ai_story',
      body: <String, dynamic>{'story_id': storyId},
      clearSidOnNotFound: false,
    );
    return ActionStatusResp.fromJson(json);
  }

  Future<GameStartResp> start({int? seed}) async {
    final json = await _postJson(
      '/v1/game/start',
      body: <String, dynamic>{if (seed != null) 'seed': seed},
      clearSidOnNotFound: false,
    );

    final data = GameStartResp.fromJson(json);
    if (data.sessionId.isEmpty) {
      throw ApiException('start missing session_id',
          statusCode: 200, body: jsonEncode(json));
    }
    await saveSessionId(data.sessionId);
    return data;
  }

  Future<GameStepResp> choose({required int choiceIndex}) async {
    final sid = await loadSessionId();
    if (sid == null)
      throw ApiException('choose failed: no session_id (call start first)');

    final json = await _postJson(
      '/v1/game/choose',
      body: <String, dynamic>{'session_id': sid, 'choice_index': choiceIndex},
    );
    return GameStepResp.fromJson(json);
  }

  Future<GameStepResp> replay() async {
    final sid = await loadSessionId();
    if (sid == null)
      throw ApiException('replay failed: no session_id (call start first)');

    final json = await _postJson(
      '/v1/game/replay',
      body: <String, dynamic>{'session_id': sid},
    );
    return GameStepResp.fromJson(json);
  }

  Future<GameStepResp> endFlow({required String endAction}) async {
    final sid = await loadSessionId();
    if (sid == null)
      throw ApiException('end_flow failed: no session_id (call start first)');

    final json = await _postJson(
      '/v1/game/end_flow',
      body: <String, dynamic>{'session_id': sid, 'end_action': endAction},
    );
    return GameStepResp.fromJson(json);
  }

  Future<GameStepResp> setReasons({
    required List<String> reasonIds,
    String reasonText = '',
  }) async {
    final sid = await loadSessionId();
    if (sid == null)
      throw ApiException(
          'set_reasons failed: no session_id (call start first)');

    final json = await _postJson(
      '/v1/game/set_reasons',
      body: <String, dynamic>{
        'session_id': sid,
        'reason_ids': reasonIds,
        'reason_text': reasonText,
      },
    );
    return GameStepResp.fromJson(json);
  }

  // ----------------------------
  // Option B: Accuse evaluator
  // ----------------------------

  Future<AccuseEvaluateResponseV2> accuseEvaluate({
    required String recognizedText,
    String? nodeId,
  }) async {
    final sid = await loadSessionId();
    if (sid == null)
      throw ApiException(
          'accuse_evaluate failed: no session_id (call start first)');

    final req = AccuseEvaluateRequestV2(
        sessionId: sid, recognizedText: recognizedText, nodeId: nodeId);

    final json = await _postJson(
      '/v1/game/accuse_evaluate',
      body: req.toJson(),
      clearSidOnNotFound: false,
    );
    return AccuseEvaluateResponseV2.fromJson(json);
  }

  Future<GameStepResp> confirmQuiz({
    required List<Object?> answers,
    bool skipped = false,
  }) async {
    final sid = await loadSessionId();
    if (sid == null)
      throw ApiException(
          'confirm_quiz failed: no session_id (call start first)');

    final json = await _postJson(
      '/v1/game/confirm_quiz',
      body: <String, dynamic>{
        'session_id': sid,
        'answers': answers,
        'skipped': skipped,
      },
    );
    return GameStepResp.fromJson(json);
  }

  void dispose() => _client.close();
}
