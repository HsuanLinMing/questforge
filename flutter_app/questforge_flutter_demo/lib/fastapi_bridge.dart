// lib/fastapi_bridge.dart
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

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
      bundle: (json['bundle'] as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{},
      events: (json['events'] as List?)?.map((e) => e.toString()).toList() ?? <String>[],
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
    required this.baseUrl,
    http.Client? client,
  }) : _client = client ?? http.Client();

  final String baseUrl; // e.g. http://127.0.0.1:8003
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
      throw ApiException('request failed', statusCode: resp.statusCode, body: resp.body);
    }

    try {
      final json = jsonDecode(resp.body);
      if (json is Map<String, dynamic>) return json;
      if (json is Map) return json.cast<String, dynamic>();
      throw ApiException('invalid json (not a map)', statusCode: resp.statusCode, body: resp.body);
    } catch (e) {
      throw ApiException('invalid json decode: $e', statusCode: resp.statusCode, body: resp.body);
    }
  }

  // ----------------------------
  // APIs (全部回 GameStepResp)
  // ----------------------------

  Future<GameStartResp> start({int? seed}) async {
    final json = await _postJson(
      '/v1/game/start',
      body: <String, dynamic>{if (seed != null) 'seed': seed},
      clearSidOnNotFound: false,
    );

    final data = GameStartResp.fromJson(json);
    if (data.sessionId.isEmpty) {
      throw ApiException('start missing session_id', statusCode: 200, body: jsonEncode(json));
    }
    await saveSessionId(data.sessionId);
    return data;
  }

  Future<GameStepResp> choose({required int choiceIndex}) async {
    final sid = await loadSessionId();
    if (sid == null) throw ApiException('choose failed: no session_id (call start first)');

    final json = await _postJson(
      '/v1/game/choose',
      body: <String, dynamic>{'session_id': sid, 'choice_index': choiceIndex},
    );
    return GameStepResp.fromJson(json);
  }

  Future<GameStepResp> replay() async {
    final sid = await loadSessionId();
    if (sid == null) throw ApiException('replay failed: no session_id (call start first)');

    final json = await _postJson(
      '/v1/game/replay',
      body: <String, dynamic>{'session_id': sid},
    );
    return GameStepResp.fromJson(json);
  }

  Future<GameStepResp> endFlow({required String endAction}) async {
    final sid = await loadSessionId();
    if (sid == null) throw ApiException('end_flow failed: no session_id (call start first)');

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
    if (sid == null) throw ApiException('set_reasons failed: no session_id (call start first)');

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

  Future<GameStepResp> confirmQuiz({
    required List<Object?> answers,
    bool skipped = false,
  }) async {
    final sid = await loadSessionId();
    if (sid == null) throw ApiException('confirm_quiz failed: no session_id (call start first)');

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
