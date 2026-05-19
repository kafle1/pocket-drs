import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';

enum DrsButtonStyle { primary, secondary, danger, ghost }

/// Primary action button — sharp 4px corner, wide-tracked CAPS label.
class DrsButton extends StatelessWidget {
  const DrsButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.style = DrsButtonStyle.primary,
    this.icon,
    this.expanded = true,
    this.loading = false,
  });

  final String label;
  final VoidCallback? onPressed;
  final DrsButtonStyle style;
  final IconData? icon;
  final bool expanded;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    final (bg, fg, borderColor) = switch (style) {
      DrsButtonStyle.primary => (scheme.onSurface, scheme.surface, scheme.onSurface),
      DrsButtonStyle.secondary => (Colors.transparent, scheme.onSurface, scheme.outline),
      DrsButtonStyle.danger => (AppColors.signalRed, AppColors.bone, AppColors.signalRed),
      DrsButtonStyle.ghost => (Colors.transparent, scheme.onSurfaceVariant, Colors.transparent),
    };

    final disabled = onPressed == null || loading;

    final child = Padding(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.xl,
        vertical: AppSpacing.lg,
      ),
      child: Row(
        mainAxisSize: expanded ? MainAxisSize.max : MainAxisSize.min,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          if (loading)
            SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                valueColor: AlwaysStoppedAnimation(fg),
              ),
            )
          else if (icon != null)
            Icon(icon, size: 16, color: disabled ? fg.withValues(alpha: 0.4) : fg),
          if ((icon != null || loading)) const SizedBox(width: AppSpacing.md),
          Text(
            label.toUpperCase(),
            style: TextStyle(
              color: disabled ? fg.withValues(alpha: 0.4) : fg,
              fontSize: 12,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.6,
            ),
          ),
        ],
      ),
    );

    return Material(
      color: disabled ? bg.withValues(alpha: 0.5) : bg,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.sm),
        side: BorderSide(
          color: disabled ? borderColor.withValues(alpha: 0.3) : borderColor,
          width: 1,
        ),
      ),
      child: InkWell(
        onTap: disabled ? null : onPressed,
        borderRadius: BorderRadius.circular(AppRadius.sm),
        child: child,
      ),
    );
  }
}
