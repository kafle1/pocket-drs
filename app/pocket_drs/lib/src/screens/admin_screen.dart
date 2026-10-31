import 'dart:async';

import 'package:flutter/material.dart';

import '../account/account.dart';
import '../api/analysis_result.dart';
import '../api/pocket_drs_api.dart';
import '../theme/app_spacing.dart';

String _count(Object? n, String one, [String? many]) {
  final v = n is num ? n.toInt() : 0;
  return '$v ${v == 1 ? one : (many ?? '${one}s')}';
}

const _months = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];

// the server sends unix seconds
String _day(Object? s, {bool time = false}) {
  if (s is! num || s <= 0) return 'never';
  final d = DateTime.fromMillisecondsSinceEpoch(s.toInt() * 1000);
  final day = '${d.day} ${_months[d.month - 1]}';
  if (!time) return day;
  String two(int x) => x.toString().padLeft(2, '0');
  return '$day, ${two(d.hour)}:${two(d.minute)}';
}

String _outcome(Map<String, Object?> j) => switch (j['status']) {
  'failed' => 'Failed',
  'succeeded' => LbwDecisionKey.parse(j['decision']).label,
  _ => 'Checking',
};

/// Admin panel: stats, people, phones and recent reviews.
class AdminScreen extends StatefulWidget {
  const AdminScreen({super.key});

  @override
  State<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends State<AdminScreen>
    with SingleTickerProviderStateMixin {
  final _api = PocketDrsApi();
  final _search = TextEditingController();
  late final _tabs = TabController(length: 3, vsync: this);
  Timer? _debounce;
  // bumped on each load, so a slow older load can't overwrite a newer one
  int _load = 0;
  bool _loading = true;
  bool _acting = false;
  String? _error;
  // whose reviews the Reviews tab shows; null is everyone
  String? _reviewsOf;
  Map<String, Object?>? _stats;
  List<Map<String, Object?>> _users = const [];
  List<Map<String, Object?>> _devices = const [];
  List<Map<String, Object?>> _jobs = const [];

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    _tabs.dispose();
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
      final jobs = _api.adminJobs(_reviewsOf);
      // if one fails first, the others' errors still need a listener
      users.ignore();
      devices.ignore();
      jobs.ignore();
      final stats = await _api.adminStats();
      final u = await users;
      final d = await devices;
      final j = await jobs;
      if (!mounted || load != _load) return;
      setState(() {
        _stats = stats;
        _users = u;
        _devices = d;
        _jobs = j;
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

  void _say(String text) => ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(text)));

  void _onSearch(String _) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), _refresh);
  }

  void _showReviews(String? email) {
    setState(() => _reviewsOf = email);
    _tabs.animateTo(2);
    _refresh();
  }

  Future<void> _act(
    String action,
    String done,
    Future<void> Function() call,
  ) async {
    if (_acting) return;
    setState(() => _acting = true);
    try {
      await call();
      Account.instance.logEvent('admin_action', {'action': action});
      if (!mounted) return;
      _say(done);
      unawaited(_refresh());
      // the admin may have changed their own row's uses
      unawaited(Account.instance.refreshMe());
    } catch (e) {
      if (mounted) _say(_message(e));
    } finally {
      if (mounted) setState(() => _acting = false);
    }
  }

  Future<void> _setUser(
    String email,
    String action, {
    String? plan,
    bool resetUsed = false,
  }) => _act(
    action,
    'Saved for $email.',
    () => _api.adminUpdateUser(email, plan: plan, resetUsed: resetUsed),
  );

  Future<void> _addPerson() async {
    final controller = TextEditingController();
    final email = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Give premium'),
        content: TextField(
          controller: controller,
          autofocus: true,
          keyboardType: TextInputType.emailAddress,
          autocorrect: false,
          decoration: const InputDecoration(
            labelText: 'Email to give premium',
            helperText: 'Works before they sign in for the first time.',
          ),
          onSubmitted: (v) => Navigator.pop(context, v),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, controller.text),
            child: const Text('Give premium'),
          ),
        ],
      ),
    );
    controller.dispose();
    final e = email?.trim().toLowerCase() ?? '';
    if (e.isEmpty || !mounted) return;
    if (!RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(e)) {
      _say("That doesn't look like an email address.");
      return;
    }
    await _setUser(e, 'add_premium', plan: 'premium');
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final s = _stats;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Admin'),
        actions: [
          IconButton(
            tooltip: 'Give premium',
            icon: const Icon(Icons.person_add_alt),
            onPressed: _acting ? null : _addPerson,
          ),
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: _loading ? null : _refresh,
          ),
        ],
        bottom: TabBar(
          controller: _tabs,
          tabs: const [
            Tab(text: 'People'),
            Tab(text: 'Phones'),
            Tab(text: 'Reviews'),
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
              s == null
                  ? ' '
                  : '${_count(s['users'], 'person', 'people')}, ${s['premium'] ?? 0} premium. '
                        'Reviews today ${s['jobs_today'] ?? 0}, failed today ${s['failed_today'] ?? 0}, '
                        'all time ${s['jobs_total'] ?? 0}.',
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
                isDense: true,
              ),
            ),
          ),
          if (_loading) const LinearProgressIndicator(),
          if (_error case final error?)
            Padding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: Text(
                error,
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: scheme.error,
                ),
              ),
            ),
          Expanded(
            child: TabBarView(
              controller: _tabs,
              children: [
                _list(_users, 'Nobody matches.', _userTile),
                _list(_devices, 'No phones yet.', _deviceTile),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (_reviewsOf case final who?)
                      ListTile(
                        title: Text(
                          'Reviews by $who',
                          overflow: TextOverflow.ellipsis,
                        ),
                        trailing: TextButton(
                          onPressed: () => _showReviews(null),
                          child: const Text('Show everyone'),
                        ),
                      ),
                    Expanded(child: _list(_jobs, 'No reviews yet.', _jobTile)),
                  ],
                ),
              ],
            ),
          ),
        ],
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
    final limit = Account.instance.me.value?.freeLimit ?? 5;
    final planText = switch (plan) {
      'admin' => 'Admin',
      'premium' => 'Premium',
      _ => 'Free, ${u['used'] ?? 0} of $limit used',
    };
    return ListTile(
      title: Text(email, overflow: TextOverflow.ellipsis),
      subtitle: Text(
        '${name.isEmpty ? '' : '$name. '}$planText. '
        '${_count(u['jobs'], 'review')}. Last seen ${_day(u['last_seen'])}.',
      ),
      onTap: email.isEmpty ? null : () => _showReviews(email),
      // an admin's plan can't be changed
      trailing: plan == 'admin' || email.isEmpty
          ? null
          : PopupMenuButton<String>(
              tooltip: 'Change plan',
              enabled: !_acting,
              onSelected: (v) => switch (v) {
                'premium' => _setUser(email, 'make_premium', plan: 'premium'),
                'free' => _setUser(email, 'make_free', plan: 'free'),
                _ => _setUser(email, 'reset_used', resetUsed: true),
              },
              itemBuilder: (_) => [
                if (plan == 'premium')
                  const PopupMenuItem(value: 'free', child: Text('Make free'))
                else
                  const PopupMenuItem(
                    value: 'premium',
                    child: Text('Make premium'),
                  ),
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
    final limit = Account.instance.me.value?.freeLimit ?? 5;
    return ListTile(
      title: Text(id.length > 20 ? '${id.substring(0, 20)}...' : id),
      subtitle: Text(
        '${d['used'] ?? 0} of $limit free used. '
        'Last used by ${last.isEmpty ? 'nobody' : last}, ${_day(d['last_seen'])}.',
      ),
      trailing: id.isEmpty
          ? null
          : TextButton(
              onPressed: _acting
                  ? null
                  : () => _act(
                      'reset_device',
                      'Phone reset.',
                      () => _api.adminResetDevice(id),
                    ),
              child: const Text('Reset'),
            ),
    );
  }

  Widget _jobTile(Map<String, Object?> j) {
    final email = '${j['email'] ?? ''}';
    return ListTile(
      title: Text(_outcome(j)),
      subtitle: Text(
        '${email.isEmpty ? 'Unknown' : email}, ${_day(j['created_at'], time: true)}',
        overflow: TextOverflow.ellipsis,
      ),
      onTap: email.isEmpty || _reviewsOf != null
          ? null
          : () => _showReviews(email),
    );
  }
}
