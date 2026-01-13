import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

class PythonBridge {
  Process? _proc;
  StreamSubscription<String>? _sub;
  StreamSubscription<String>? _errSub;

  final _outCtrl = StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get outputs => _outCtrl.stream;

  bool get isRunning => _proc != null;

  Future<void> start({
    required String workingDir,
    String module = 'questforge.cli.json_bridge',
    List<String> args = const [],
    String? pythonBin,
  }) async {
    if (kIsWeb) throw StateError('Web 不支援 Process bridge');
    if (!Platform.isMacOS && !Platform.isWindows && !Platform.isLinux) {
      throw StateError('目前只有桌面平台支援 dev-only bridge');
    }
    if (_proc != null) return;

    try {
      final absWorkingDir = _ensureAbsoluteExistingDir(workingDir);

      final pyExe = await _resolvePythonExe(
        workingDir: absWorkingDir,
        preferred: pythonBin,
      );

      _proc = await Process.start(
        pyExe,
        ['-m', module, ...args],
        workingDirectory: absWorkingDir,
        runInShell: false,
        environment: <String, String>{
          ...Platform.environment,
          'PYTHONUNBUFFERED': '1',
        },
      );

      _outCtrl.add({
        'type': 'bridge_started',
        'python': pyExe,
        'working_dir': absWorkingDir,
        'module': module,
        'args': args,
      });

      _sub = _proc!.stdout.transform(utf8.decoder).transform(const LineSplitter()).listen(_handleStdoutLine);

      _errSub = _proc!.stderr.transform(utf8.decoder).transform(const LineSplitter()).listen((line) {
        debugPrint('[QF][BRIDGE][STDERR] $line'); // ✅ 加這行
        _outCtrl.add({'type': 'stderr', 'message': line});
      });

      _proc!.exitCode.then((code) {
        _outCtrl.add({'type': 'exit', 'code': code});
        stop();
      });
    } catch (e, st) {
      // ✅ 讓 UI 看得到錯誤，不要卡在 Starting...
      _outCtrl.add({
        'type': 'start_error',
        'message': e.toString(),
        'stack': st.toString(),
      });
      await stop();
      rethrow;
    }
  }

  void _handleStdoutLine(String line) {
    debugPrint('[QF][BRIDGE][STDOUT] $line'); // ✅ 加這行
    final trimmed = line.trim();
    if (trimmed.isEmpty) return;

    try {
      final obj = jsonDecode(trimmed);
      if (obj is Map) {
        _outCtrl.add(Map<String, dynamic>.from(obj));
      } else {
        _outCtrl.add({'type': 'log', 'message': trimmed});
      }
    } catch (_) {
      _outCtrl.add({'type': 'log', 'message': trimmed});
    }
  }

  void send(Map<String, dynamic> payload) {
    final p = _proc;

    debugPrint('[QF][BRIDGE][SEND] running=${p != null} payload=${jsonEncode(payload)}');

    if (p == null) {
      debugPrint('[QF][BRIDGE][SEND][DROP] process is null (bridge not running)');
      return;
    }

    p.stdin.writeln(jsonEncode(payload));
  }

  Future<void> stop() async {
    await _sub?.cancel();
    await _errSub?.cancel();
    _sub = null;
    _errSub = null;

    final p = _proc;
    _proc = null;
    if (p != null) {
      try {
        p.kill(ProcessSignal.sigterm);
      } catch (_) {}
    }
  }

  void dispose() {
    stop();
    _outCtrl.close();
  }

  // ------------------------------------------------------------
  // helpers
  // ------------------------------------------------------------

  static String _ensureAbsoluteExistingDir(String input) {
    final s = input.trim();
    if (s.isEmpty) throw ArgumentError('workingDir is empty');

    // ⚠️ macOS app 下相對路徑很容易指到 sandbox，建議直接強制要求絕對路徑
    final dir = Directory(s);
    if (!dir.isAbsolute) {
      throw ArgumentError(
        'workingDir 必須是「絕對路徑」\n'
        '你傳的是：$s\n'
        '例如：/Users/user/Projects/QUESTFORGE',
      );
    }
    if (!dir.existsSync()) {
      throw ArgumentError('workingDir not found: $s');
    }
    return dir.absolute.path;
  }

  static Future<String> _resolvePythonExe({
    required String workingDir,
    String? preferred,
  }) async {
    // 1) user specified
    if (preferred != null && preferred.trim().isNotEmpty) {
      final p = preferred.trim();
      if (_looksLikePath(p)) {
        if (await _canExecute(p)) return p;
        throw StateError('指定的 pythonBin 不存在或不可執行：$p');
      }
      final resolved = await _which(p);
      if (resolved != null) return resolved;
      throw StateError('找不到 $p（PATH 中不存在）');
    }

    // 2) venv in project root
    final venvCandidates = <String>[
      if (Platform.isWindows) '$workingDir\\.venv\\Scripts\\python.exe' else '$workingDir/.venv/bin/python',
      if (Platform.isWindows) '$workingDir\\venv\\Scripts\\python.exe' else '$workingDir/venv/bin/python',
    ];
    for (final c in venvCandidates) {
      if (await _canExecute(c)) return c;
    }

    // 3) PATH
    final pathPy3 = await _which(Platform.isWindows ? 'python' : 'python3');
    if (pathPy3 != null) return pathPy3;

    final pathPy = await _which('python');
    if (pathPy != null) return pathPy;

    // 4) common macOS
    if (Platform.isMacOS) {
      const macCandidates = <String>[
        '/opt/homebrew/bin/python3',
        '/usr/local/bin/python3',
      ];
      for (final c in macCandidates) {
        if (await _canExecute(c)) return c;
      }
    }

    throw StateError(
      '找不到可用的 Python。\n'
      '建議在 start() 傳入 pythonBin，例如：\n'
      '- /opt/homebrew/bin/python3\n'
      '- $workingDir/.venv/bin/python\n',
    );
  }

  static bool _looksLikePath(String v) => v.contains('/') || v.contains('\\');

  static Future<bool> _canExecute(String path) async {
    try {
      final f = File(path);
      if (!f.existsSync()) return false;

      // Windows: existence is enough.
      if (Platform.isWindows) return true;

      // mac/linux: check executable bit (avoid Process.run due to sandbox)
      final st = f.statSync();
      final mode = st.mode; // POSIX permission bits are in low 9 bits.
      final isExecutable = (mode & 0x49) != 0; // 0o111 = 73 = 0x49
      return isExecutable;
    } catch (_) {
      return false;
    }
  }

  static Future<String?> _which(String cmd) async {
    try {
      if (Platform.isWindows) {
        final r = await Process.run('where', [cmd]);
        if (r.exitCode != 0) return null;
        final out = (r.stdout ?? '').toString().trim();
        if (out.isEmpty) return null;
        return out.split(RegExp(r'[\r\n]+')).first.trim();
      } else {
        final r = await Process.run('which', [cmd]);
        if (r.exitCode != 0) return null;
        final out = (r.stdout ?? '').toString().trim();
        return out.isEmpty ? null : out;
      }
    } catch (_) {
      return null;
    }
  }
}
