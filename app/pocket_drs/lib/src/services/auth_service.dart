import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:google_sign_in/google_sign_in.dart';

class AuthService {
  final FirebaseAuth _auth = FirebaseAuth.instance;
  final GoogleSignIn _googleSignIn = GoogleSignIn();

  User? get currentUser => _auth.currentUser;
  Stream<User?> get authStateChanges => _auth.authStateChanges();

  bool get isAuthenticated => currentUser != null;
  String? get userId => currentUser?.uid;
  String? get userEmail => currentUser?.email;
  String? get userName => currentUser?.displayName;
  String? get userPhotoUrl => currentUser?.photoURL;

  /// Sign in with Google.
  ///
  /// On web we route through Firebase's own popup OAuth flow
  /// (``FirebaseAuth.signInWithPopup``) so the page does not need a
  /// ``google-signin-client_id`` meta tag and we do not need to register
  /// a separate web OAuth client beyond the one Firebase auto-creates
  /// when Google is enabled as a sign-in method in the project. The
  /// ``google_sign_in`` package's web init throws ``appClientId != null``
  /// when no meta tag is set, so it is bypassed entirely on the web build.
  ///
  /// On native (Android/iOS) the platform's Google Sign-In client supplies
  /// the OAuth credential, which we then exchange for a Firebase credential
  /// — the established mobile flow.
  Future<UserCredential?> signInWithGoogle() async {
    if (kIsWeb) {
      final provider = GoogleAuthProvider()
        ..addScope('email')
        ..addScope('profile');
      return _auth.signInWithPopup(provider);
    }

    final googleUser = await _googleSignIn.signIn();
    if (googleUser == null) return null;
    final googleAuth = await googleUser.authentication;
    final credential = GoogleAuthProvider.credential(
      accessToken: googleAuth.accessToken,
      idToken: googleAuth.idToken,
    );
    return _auth.signInWithCredential(credential);
  }

  Future<void> signOut() async {
    final futures = <Future<void>>[_auth.signOut()];
    if (!kIsWeb) futures.add(_googleSignIn.signOut());
    await Future.wait(futures);
  }
}
