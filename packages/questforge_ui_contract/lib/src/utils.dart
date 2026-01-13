typedef JsonMap = Map<String, dynamic>;

abstract interface class JsonCodable {
  JsonMap toJson();
}

/// Normalize any json-like input into JsonMap.
/// - Map<String,dynamic> => itself
/// - Map => cast keys to String if possible
/// - otherwise => empty
JsonMap normalizeJsonMap(Object? json) {
  if (json is Map<String, dynamic>) return json;
  if (json is Map) {
    final out = <String, dynamic>{};
    for (final e in json.entries) {
      out['${e.key}'] = e.value;
    }
    return out;
  }
  return <String, dynamic>{};
}

Object? pick(JsonMap m, String key) => m[key];

String asString(Object? v, [String fallback = '']) {
  if (v == null) return fallback;
  if (v is String) return v;
  return v.toString();
}

int asInt(Object? v, [int fallback = 0]) {
  if (v == null) return fallback;
  if (v is int) return v;
  if (v is num) return v.toInt();
  if (v is String) {
    final x = int.tryParse(v.trim());
    return x ?? fallback;
  }
  return fallback;
}

bool asBool(Object? v, [bool fallback = false]) {
  if (v == null) return fallback;
  if (v is bool) return v;
  if (v is num) return v != 0;
  if (v is String) {
    final s = v.trim().toLowerCase();
    if (s == 'true' || s == '1' || s == 'yes') return true;
    if (s == 'false' || s == '0' || s == 'no') return false;
  }
  return fallback;
}

List<T> asListOf<T>(Object? v, T Function(Object?) map) {
  if (v is List) {
    return v.map(map).toList(growable: false);
  }
  return List<T>.empty(growable: false);
}
