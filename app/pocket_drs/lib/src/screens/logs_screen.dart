import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../utils/analysis_logger.dart';
import '../utils/log_exporter.dart';

class LogsScreen extends StatefulWidget {
  const LogsScreen({
    super.key,
    this.autoLoad = true,
    this.initialText,
    this.initialPath,
  });

  /// When true (default), the screen will load logs from [AnalysisLogger].
  ///
  /// This can be set to false in widget tests to avoid depending on platform
  /// filesystem plugins.
  final bool autoLoad;

  /// Optional injected contents (used when [autoLoad] is false).
  final String? initialText;

  /// Optional injected path/locator (used when [autoLoad] is false).
  final String? initialPath;

  @override
  State<LogsScreen> createState() => _LogsScreenState();
}

class _LogsScreenState extends State<LogsScreen> {
  String _text = '';
  bool _loading = true;
  String? _path;

  @override
  void initState() {
    super.initState();
    if (widget.autoLoad) {
      _load();
    } else {
      _text = widget.initialText ?? '';
      _path = widget.initialPath;
      _loading = false;
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
    });

    final logger = AnalysisLogger.instance;
    final text = await logger.readAll();
    final path = await logger.logPath();

    if (!mounted) return;
    setState(() {
      _text = text;
      _path = path;
      _loading = false;
    });
  }

  Future<void> _copy() async {
    await Clipboard.setData(ClipboardData(text: _text));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Logs copied to clipboard')),
    );
  }

  Future<void> _copyPath() async {
    final p = _path;
    if (p == null || p.isEmpty) return;
    await Clipboard.setData(ClipboardData(text: p));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Log location copied')),
    );
  }

  Future<void> _export() async {
    final contents = _text;
    if (contents.isEmpty) return;
    final ts = DateTime.now().toIso8601String().replaceAll(':', '-');
    await exportTextFile(filename: 'pocket_drs_logs_$ts.txt', contents: contents);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Log export started')),
    );
  }

  Future<void> _clear() async {
    await AnalysisLogger.instance.clear();
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Logs'),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            onPressed: _loading ? null : _load,
            icon: const Icon(Icons.refresh),
          ),
          IconButton(
            tooltip: 'Export',
            onPressed: _loading || _text.isEmpty ? null : _export,
            icon: const Icon(Icons.download),
          ),
          IconButton(
            tooltip: 'Copy',
            onPressed: _loading || _text.isEmpty ? null : _copy,
            icon: const Icon(Icons.copy),
          ),
          IconButton(
            tooltip: 'Copy location',
            onPressed: _loading || _path == null ? null : _copyPath,
            icon: const Icon(Icons.link),
          ),
          IconButton(
            tooltip: 'Clear',
            onPressed: _loading ? null : _clear,
            icon: const Icon(Icons.delete_outline),
          ),
        ],
      ),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      'Logs are saved for debugging, but not shown in-app.',
                      style: theme.textTheme.titleMedium,
                    ),
                    const SizedBox(height: 8),
                    Text(
                      _path == null
                          ? 'Location: (unavailable)'
                          : 'Location: $_path',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 12),
                    Wrap(
                      spacing: 12,
                      runSpacing: 12,
                      children: [
                        FilledButton.icon(
                          onPressed: _loading || _text.isEmpty ? null : _export,
                          icon: const Icon(Icons.download),
                          label: const Text('Export'),
                        ),
                        OutlinedButton.icon(
                          onPressed: _loading || _text.isEmpty ? null : _copy,
                          icon: const Icon(Icons.copy),
                          label: const Text('Copy'),
                        ),
                        OutlinedButton.icon(
                          onPressed: _loading || _path == null ? null : _copyPath,
                          icon: const Icon(Icons.link),
                          label: const Text('Copy location'),
                        ),
                        OutlinedButton.icon(
                          onPressed: _loading ? null : _clear,
                          icon: const Icon(Icons.delete_outline),
                          label: const Text('Clear'),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Text(
                      _text.isEmpty
                          ? 'No logs yet.'
                          : 'Logs captured: ${_text.length} characters',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
      ),
    );
  }
}
