import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';

import '../utils/app_settings.dart';
import 'logs_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _urlController = TextEditingController();
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final url = await AppSettings.getServerUrl();
    if (!mounted) return;
    setState(() {
      _urlController.text = url.isNotEmpty
          ? url
          : (kIsWeb ? 'http://localhost:8000' : '');
      _loading = false;
    });
  }

  @override
  void dispose() {
    _urlController.dispose();
    super.dispose();
  }

  bool _looksLikeUrl(String s) {
    if (s.trim().isEmpty) return false;
    final uri = Uri.tryParse(s.trim());
    return uri != null && uri.hasScheme && uri.host.isNotEmpty;
  }

  Future<void> _save() async {
    final url = _urlController.text.trim();
    if (!_looksLikeUrl(url)) {
      setState(() => _error = 'Enter a valid server URL like http://192.168.1.10:8000');
      return;
    }

    setState(() => _error = null);
    await AppSettings.setServerUrl(url);

    if (!mounted) return;
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Settings'),
        actions: [
          TextButton(
            onPressed: _loading ? null : _save,
            child: const Text('Save'),
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
                    TextField(
                      controller: _urlController,
                      keyboardType: TextInputType.url,
                      decoration: const InputDecoration(
                        labelText: 'Server URL',
                        hintText: 'http://192.168.1.10:8000',
                        border: OutlineInputBorder(),
                      ),
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      Text(_error!, style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.error)),
                    ],
                    const SizedBox(height: 12),
                    OutlinedButton.icon(
                      onPressed: () async {
                        await Navigator.of(context).push(
                          MaterialPageRoute(builder: (_) => const LogsScreen()),
                        );
                      },
                      icon: const Icon(Icons.receipt_long),
                      label: const Text('View logs'),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'Tip: for a physical Android phone, use your laptop\'s LAN IP (not localhost).\n\nExample: start the server on your laptop and set this to http://<laptop-ip>:8000',
                      style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    ),
                  ],
                ),
              ),
      ),
    );
  }
}
