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
                      const _StatRow(),
                      const SizedBox(height: AppSpacing.xl),
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

class _StatRow extends StatelessWidget {
  const _StatRow();

  @override
  Widget build(BuildContext context) {
    return const Row(
      children: [
        Expanded(
          child: _MiniStat(label: 'PITCH-LEN', value: '20.12', unit: 'M'),
        ),
        SizedBox(width: AppSpacing.lg),
        Expanded(
          child: _MiniStat(label: 'PITCH-W', value: '3.05', unit: 'M'),
        ),
        SizedBox(width: AppSpacing.lg),
        Expanded(
          child: _MiniStat(label: 'STUMPS', value: '0.71', unit: 'M'),
        ),
      ],
    );
  }
}

class _MiniStat extends StatelessWidget {
  const _MiniStat({
    required this.label,
    required this.value,
    required this.unit,
  });
  final String label;
  final String value;
  final String unit;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: theme.textTheme.labelSmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: AppSpacing.sm),
        Row(
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: [
            Text(
              value,
              style: AppTypography.mono(theme.textTheme.headlineMedium),
            ),
            const SizedBox(width: 2),
            Text(
              unit,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ),
      ],
    );
  }
}
