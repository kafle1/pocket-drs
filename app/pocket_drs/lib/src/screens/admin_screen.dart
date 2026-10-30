import 'dart:async';

import 'package:flutter/material.dart';

import '../account/account.dart';
import '../api/pocket_drs_api.dart';
import '../theme/app_spacing.dart';

/// Admin panel: stats, people with their plan and uses, and devices.
class AdminScreen extends StatefulWidget {
  const AdminScreen({super.key});

  @override
  State<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends State<AdminScreen> {
  final _api = PocketDrsApi(baseUrl: kServerUrl);
  final _search = TextEditingController();
  Timer? _debounce;
  // bumped on each load, so a slow older search can't overwrite a newer one
  int _load = 0;
  bool _loading = true;
  String? _error;
  Map<String, Object?>? _stats;
  List<Map<String, Object?>> _users = const [];
  List<Map<String, Object?>> _devices = const [];

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    _api.close();
    super.dispose();
  }

  Future<void> _refresh() async {
    final load = ++_load;
    setState(() {
      _loading = true;
      _error = null;
    });
    final q = _search.text;
    try {
      final users = _api.adminUsers(q);
      final devices = _api.adminDevices(q);
      // if stats fails first, the other two errors still need a listener
      users.ignore();
      devices.ignore();
      final stats = await _api.adminStats();
      final u = await users;
      final d = await devices;
      if (!mounted || load != _load) return;
      setState(() {
        _stats = stats;
        _users = u;
        _devices = d;
        _loading = false;
      });
    } catch (e) {
      if (!mounted || load != _load) return;
      setState(() {
        _loading = false;
        _error = _message(e);
      });
    }
  }

  String _message(Object e) =>
      e is ApiException ? e.message : 'Something went wrong. Try again.';

  void _onSearch(String _) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), _refresh);
  }

  Future<void> _act(String action, Future<void> Function() call) async {
    try {
      await call();
      Account.instance.logEvent('admin_action', {'action': action});
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Done.')));
      unawaited(_refresh());
      // the admin may have changed their own row's uses
      unawaited(Account.instance.refreshMe());
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(_message(e))));
    }
  }

  Future<void> _addPerson() async {
    final controller = TextEditingController();
    final email = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Add a person'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'They get premium now, and keep it when they first sign in.',
            ),
            const SizedBox(height: AppSpacing.md),
            TextField(
              controller: controller,
              autofocus: true,
              keyboardType: TextInputType.emailAddress,
              autocorrect: false,
              decoration: const InputDecoration(
                labelText: 'Gmail address',
                border: OutlineInputBorder(),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, controller.text),
            child: const Text('Make premium'),
          ),
        ],
      ),
    );
    controller.dispose();
    final e = email?.trim().toLowerCase() ?? '';
    if (e.isEmpty || !mounted) return;
    if (!RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(e)) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('That does not look like an email.')),
      );
      return;
    }
    await _act('add_premium', () => _api.adminUpdateUser(e, plan: 'premium'));
  }

  String _stat(String key) => '${_stats?[key] ?? 0}';

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Admin'),
          actions: [
            IconButton(
              tooltip: 'Add a person',
              icon: const Icon(Icons.person_add_alt),
              onPressed: _addPerson,
            ),
            IconButton(
              tooltip: 'Refresh',
              icon: const Icon(Icons.refresh),
              onPressed: _loading ? null : _refresh,
            ),
          ],
          bottom: const TabBar(
            tabs: [
              Tab(text: 'People'),
              Tab(text: 'Phones'),
            ],
          ),
        ),
        body: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.lg,
                AppSpacing.md,
                AppSpacing.lg,
                0,
              ),
              child: Text(
                _stats == null
                    ? ' '
                    : '${_stat('users')} people, ${_stat('premium')} premium. '
                          '${_stat('jobs_today')} reviews today '
                          '(${_stat('failed_today')} failed), '
                          '${_stat('jobs_total')} in all.',
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: scheme.onSurfaceVariant,
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: TextField(
                controller: _search,
                onChanged: _onSearch,
                keyboardType: TextInputType.emailAddress,
                autocorrect: false,
                decoration: const InputDecoration(
                  prefixIcon: Icon(Icons.search),
                  hintText: 'Search by email',
                  border: OutlineInputBorder(),
                  isDense: true,
                ),
              ),
            ),
            if (_loading) const LinearProgressIndicator(),
            if (_error case final error?)
              Padding(
                padding: const EdgeInsets.all(AppSpacing.lg),
                child: Text(error, style: TextStyle(color: scheme.error)),
              ),
            Expanded(
              child: TabBarView(
                children: [
                  _list(_users, 'No one found.', _userTile),
                  _list(_devices, 'No phones found.', _deviceTile),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _list(
    List<Map<String, Object?>> rows,
    String empty,
    Widget Function(Map<String, Object?>) tile,
  ) {
    return RefreshIndicator(
      onRefresh: _refresh,
      child: rows.isEmpty
          ? ListView(
              children: [
                if (!_loading)
                  Padding(
                    padding: const EdgeInsets.all(AppSpacing.xl),
                    child: Text(empty, textAlign: TextAlign.center),
                  ),
              ],
            )
          : ListView.separated(
              itemCount: rows.length,
              separatorBuilder: (_, _) => const Divider(height: 1),
              itemBuilder: (_, i) => tile(rows[i]),
            ),
    );
  }

  Widget _userTile(Map<String, Object?> u) {
    final email = '${u['email'] ?? ''}';
    final plan = '${u['plan'] ?? 'free'}';
    final name = '${u['name'] ?? ''}';
    final planWord = switch (plan) {
      'admin' => 'Admin',
      'premium' => 'Premium',
      _ => 'Free',
    };
    return ListTile(
      title: Text(email, overflow: TextOverflow.ellipsis),
      subtitle: Text(
        [
          if (name.isNotEmpty) name,
          '$planWord, ${u['used'] ?? 0} free used, ${u['jobs'] ?? 0} reviews',
        ].join('\n'),
      ),
      isThreeLine: name.isNotEmpty,
      // an admin's plan can't be changed from the app
      trailing: plan == 'admin' || email.isEmpty
          ? null
          : PopupMenuButton<String>(
              tooltip: 'Change',
              onSelected: (v) => switch (v) {
                'premium' => _act(
                  'make_premium',
                  () => _api.adminUpdateUser(email, plan: 'premium'),
                ),
                'free' => _act(
                  'make_free',
                  () => _api.adminUpdateUser(email, plan: 'free'),
                ),
                _ => _act(
                  'reset_used',
                  () => _api.adminUpdateUser(email, resetUsed: true),
                ),
              },
              itemBuilder: (_) => [
                if (plan != 'premium')
                  const PopupMenuItem(
                    value: 'premium',
                    child: Text('Make premium'),
                  ),
                if (plan == 'premium')
                  const PopupMenuItem(value: 'free', child: Text('Make free')),
                const PopupMenuItem(
                  value: 'reset',
                  child: Text('Reset free reviews'),
                ),
              ],
            ),
    );
  }

  Widget _deviceTile(Map<String, Object?> d) {
    final id = '${d['device_id'] ?? ''}';
    final last = '${d['last_email'] ?? ''}';
    return ListTile(
      title: Text(
        last.isEmpty ? 'Phone not signed in yet' : last,
        overflow: TextOverflow.ellipsis,
      ),
      subtitle: Text(
        '${d['used'] ?? 0} free used. Phone ${id.length > 8 ? id.substring(0, 8) : id}',
      ),
      trailing: id.isEmpty
          ? null
          : TextButton(
              onPressed: () => _act(
                'reset_device',
                () => _api.adminResetDevice(id),
              ),
              child: const Text('Reset'),
            ),
    );
  }
}
