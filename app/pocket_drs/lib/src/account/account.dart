import 'dart:async';
import 'dart:math';

import 'package:firebase_analytics/firebase_analytics.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/pocket_drs_api.dart';

const _native = MethodChannel('pocket_drs/native');
const kAdminEmail = 'kafleniraj@gmail.com';
final _validDeviceId = RegExp(r'^[A-Za-z0-9_-]{8,128}$');

/// What `/v1/me` says about the signed-in person.
class Me {
  Me({
    required this.email,
    required this.name,
    required this.plan,
    required this.isAdmin,
    required this.freeLimit,
    required this.left,
    required this.contactEmail,
  });

  final String email;
  final String name;
  final String plan;
  final bool isAdmin;
  final int freeLimit;
  // fewest reviews left on this account or this phone; null means unlimited
  final int? left;
  final String contactEmail;

  bool get usedUp => left != null && left! <= 0;

  static Me fromJson(Map<String, Object?> j) {
    int? n(Object? v) => v is num ? v.toInt() : null;
    final r = n(j['remaining']);
    final d = n(j['device_remaining']);
    final left = r == null ? d : (d == null ? r : min(r, d));
    final plan = j['plan'] is String ? j['plan'] as String : 'free';
    return Me(
      email: j['email'] is String ? j['email'] as String : '',
      name: j['name'] is String ? j['name'] as String : '',
      plan: plan,
      isAdmin: j['is_admin'] == true,
      freeLimit: n(j['free_limit']) ?? 5,
      // premium and admin come back with nulls, a free account never should
      left: plan == 'free' ? (left ?? 0) : null,
      contactEmail: j['contact_email'] is String
          ? j['contact_email'] as String
          : kAdminEmail,
    );
  }
}

/// Sign-in, the device id and the person's plan, shared by every screen.
class Account {
  Account._();
  static final instance = Account._();

  final signedIn = ValueNotifier<bool>(false);
  final me = ValueNotifier<Me?>(null);
  bool _ready = false;
  String? _deviceId;
  Future<void>? _meLoad;
  String? _meLoadUid;

  void _log(String m) => debugPrint(m);

  /// Call after Firebase is up.
  Future<void> init() async {
    try {
      await GoogleSignIn.instance.initialize();
      _ready = true;
    } catch (e) {
      _log('[AUTH] google sign-in init failed: $e');
    }
    final auth = FirebaseAuth.instance;
    signedIn.value = auth.currentUser != null;
    auth.authStateChanges().listen((u) {
      signedIn.value = u != null;
      if (u == null) me.value = null;
    });
    if (signedIn.value) unawaited(refreshMe());
  }

  Future<String> deviceId() async {
    final cached = _deviceId;
    if (cached != null) return cached;
    String? id;
    try {
      id = await _native.invokeMethod<String>('deviceId');
    } catch (e) {
      _log('[AUTH] device id: $e');
    }
    // some emulators and custom ROMs have no ANDROID_ID, so keep a random one instead
    if (id == null || !_validDeviceId.hasMatch(id)) {
      final prefs = await SharedPreferences.getInstance();
      id = prefs.getString('device_id');
      if (id == null || !_validDeviceId.hasMatch(id)) {
        final r = Random.secure();
        id = List.generate(32, (_) => r.nextInt(16).toRadixString(16)).join();
        await prefs.setString('device_id', id);
      }
    }
    return _deviceId = id;
  }

  /// Headers for every server call. [refresh] forces a new sign-in token.
  Future<Map<String, String>> headers({bool refresh = false}) async {
    String? token;
    final user = FirebaseAuth.instance.currentUser;
    if (user != null) {
      try {
        token = await user.getIdToken(refresh);
      } on FirebaseAuthException catch (e) {
        // only a removed account or a dead token signs out; anything else is worth a retry
        if (const {
          'user-token-expired',
          'user-disabled',
          'user-not-found',
          'invalid-user-token',
        }.contains(e.code)) {
          await signOut();
          throw ApiException(ApiErrorKind.signIn, kSignInAgain);
        }
        throw ApiException(ApiErrorKind.network, kCantConnect);
      }
    }
    return {
      if (token != null) 'Authorization': 'Bearer $token',
      'X-Device-Id': await deviceId(),
    };
  }

  /// Returns null when signed in, or plain words for why it didn't work.
  Future<String?> signIn() async {
    if (!_ready) {
      return "Google sign-in isn't available on this phone right now. "
          'Restart the app and try again.';
    }
    try {
      final account = await GoogleSignIn.instance.authenticate();
      final idToken = account.authentication.idToken;
      if (idToken == null) return "Couldn't sign in with Google. Try again.";
      await FirebaseAuth.instance.signInWithCredential(
        GoogleAuthProvider.credential(idToken: idToken),
      );
      logEvent('login', {'method': 'google'});
      unawaited(refreshMe());
      return null;
    } on GoogleSignInException catch (e) {
      _log('[AUTH] google: ${e.code} ${e.description}');
      return switch (e.code) {
        GoogleSignInExceptionCode.canceled =>
          "Sign-in didn't finish. Tap Continue with Google to try again.",
        GoogleSignInExceptionCode.interrupted =>
          'Sign-in was interrupted. Try again.',
        // phones without google play (newer huawei and honor) land here every time
        _ =>
          "Couldn't sign in with Google. Check your internet and try again. "
              'If it keeps failing, use the website: $kServerUrl',
      };
    } on FirebaseAuthException catch (e) {
      _log('[AUTH] firebase: ${e.code}');
      return switch (e.code) {
        'network-request-failed' =>
          "Can't reach Google. Check your internet and try again.",
        'user-disabled' =>
          'This account has been turned off. Contact the admin.',
        _ => "Couldn't sign in with Google. Try again.",
      };
    } catch (e) {
      _log('[AUTH] sign-in: $e');
      return "Couldn't sign in with Google. Try again.";
    }
  }

  Future<void> signOut() async {
    me.value = null;
    try {
      await GoogleSignIn.instance.signOut();
    } catch (_) {}
    try {
      await FirebaseAuth.instance.signOut();
    } catch (e) {
      _log('[AUTH] sign-out: $e');
    }
  }

  /// Reloads the plan and free reviews left; failures keep the last known value.
  Future<void> refreshMe() {
    // the listener may not have set signedIn yet right after signIn(), so ask Firebase
    final uid = FirebaseAuth.instance.currentUser?.uid;
    if (uid == null) return Future.value();
    final pending = _meLoad;
    if (pending != null && _meLoadUid == uid) return pending;
    _meLoadUid = uid;
    late final Future<void> load;
    load = _loadMe(uid).whenComplete(() {
      if (identical(_meLoad, load)) _meLoad = null;
    });
    return _meLoad = load;
  }

  Future<void> _loadMe(String uid) async {
    final api = PocketDrsApi();
    try {
      final next = await api.getMe();
      // a sign-out or another sign-in during the call makes this someone else's plan
      if (FirebaseAuth.instance.currentUser?.uid == uid) me.value = next;
    } catch (e) {
      _log('[AUTH] me: $e');
    } finally {
      api.close();
    }
  }

  void logEvent(String name, [Map<String, Object>? params]) {
    FirebaseAnalytics.instance
        .logEvent(name: name, parameters: params)
        .catchError((Object e) => _log('[ANALYTICS] $e'));
  }
}
