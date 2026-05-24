import 'package:flutter/material.dart';
import '../services/auth_service.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../widgets/drs_button.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _auth = AuthService();
  bool _isLoading = false;

  Future<void> _signIn() async {
    setState(() => _isLoading = true);
    try {
      await _auth.signInWithGoogle();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Sign in failed: $e')));
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }


  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;

    return Scaffold(
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: constraints.maxHeight),
              child: IntrinsicHeight(
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.xl,
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const SizedBox(height: AppSpacing.xl),
                      Row(
                        children: [
                          Text(
                            'POCKET DRS',
                            style: theme.textTheme.labelMedium?.copyWith(
                              color: scheme.onSurfaceVariant,
                            ),
                          ),
                          const SizedBox(width: AppSpacing.sm),
                          Container(
                            width: 6,
                            height: 6,
                            decoration: const BoxDecoration(
                              color: AppColors.signalRed,
                              shape: BoxShape.circle,
                            ),
                          ),
                        ],
                      ),
                      const Spacer(flex: 2),
                      Text(
                        'BALL',
                        style: AppTypography.mono(
                          theme.textTheme.displayLarge,
                        )?.copyWith(height: 0.9),
                      ),
                      Text(
                        'TRACKING.',
                        style: AppTypography.mono(
                          theme.textTheme.displayLarge,
                        )?.copyWith(color: AppColors.signalRed, height: 0.9),
                      ),
                      const SizedBox(height: AppSpacing.lg),
                      Row(
                        children: [
                          Container(
                            width: 24,
                            height: 1,
                            color: scheme.outline,
                          ),
                          const SizedBox(width: AppSpacing.md),
                          Expanded(
                            child: Text(
                              'Single-view 3D trajectory reconstruction & LBW decision review.',
                              style: theme.textTheme.bodyMedium?.copyWith(
                                color: scheme.onSurfaceVariant,
                              ),
                            ),
                          ),
                        ],
                      ),
                      const Spacer(flex: 3),
                      Container(height: 1, color: scheme.outline),
                      const SizedBox(height: AppSpacing.xl),
                      DrsButton(
                        label: 'Continue with Google',
                        onPressed: _isLoading ? null : _signIn,
                        loading: _isLoading,
                        icon: Icons.login,
                      ),
                      const SizedBox(height: AppSpacing.md),
                      Text(
                        'Your pitches stay synced across sessions.',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: scheme.onSurfaceVariant,
                        ),
                      ),
                      const SizedBox(height: AppSpacing.xl),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

