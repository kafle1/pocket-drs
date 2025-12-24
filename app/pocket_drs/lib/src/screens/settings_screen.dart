import 'package:flutter/material.dart';

import '../utils/app_settings.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _urlController = TextEditingController();
  bool _useBackend = false;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final use = await AppSettings.getUseBackend();
    final url = await AppSettings.getServerUrl();
    if (!mounted) return;
    setState(() {
      _useBackend = use;
      _urlController.text = url;
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
    if (_useBackend && !_looksLikeUrl(url)) {
      setState(() => _error = 'Enter a valid server URL like http://192.168.1.10:8000');
      return;
    }

    setState(() => _error = null);
    await AppSettings.setUseBackend(_useBackend);
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
                    SwitchListTile(
                      value: _useBackend,
                      onChanged: (v) => setState(() => _useBackend = v),
                      title: const Text('Use backend server'),
                      subtitle: const Text('Upload the clip to a laptop server for analysis.'),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: _urlController,
                      keyboardType: TextInputType.url,
                      decoration: const InputDecoration(
                        labelText: 'Server URL',
                        hintText: 'http://192.168.1.10:8000',
                        border: OutlineInputBorder(),
                      ),
                      enabled: _useBackend,
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      Text(_error!, style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.error)),
                    ],
                    const SizedBox(height: 12),
                    Text(
                      'Tip: for a physical Android phone, use your laptop\'s LAN IP (not localhost).',
                      style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    ),
                  ],
                ),
              ),
      ),
    );
  }
}
