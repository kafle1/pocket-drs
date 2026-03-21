import re

with open('app/pocket_drs/lib/src/screens/pitches_screen.dart', 'r') as f:
    text = f.read()

empty_state_old = """
                      Container(
                        width: 120,
                        height: 120,
                        decoration: BoxDecoration(
                          color: theme.colorScheme.primaryContainer,
                          shape: BoxShape.circle,
                        ),
                        child: Icon(
                          Icons.sports_cricket,
                          size: 56,
                          color: theme.colorScheme.primary,
                        ),
                      ),
                      const SizedBox(height: 24),
                      Text(
                        'No Pitches Yet',
                        style: theme.textTheme.headlineSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 12),
                      Text(
                        'Create your first pitch to get started with ball tracking and analysis.',
                        style: theme.textTheme.bodyLarge?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                        textAlign: TextAlign.center,
                      ),
"""

empty_state_new = """
                      Icon(
                        Icons.add_location_alt_outlined                        Icons.add_location_alt              color: theme.colorScheme.onSurfaceVariant.withValues(alpha: 0.5),
                      ),
                      const SizedBox(height: 24),
                      Text(
                        'No Pitches Yet',
                                           em                                           em                     nst Si                                           em                                   yo                       ta                                         
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                        textAlign: TextAlign.center,
                      ),
"""

text = text.replace(empty_state_old.strip(), empty_state_new.strip())

card_old = """
    return Dismissible(
      key: ValueKey(pitch.id),
      direction: DismissDirection.endToStart,
      confirmDismiss: (_) async {
        onDelete();
        return false;
      },
      background: Container(
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 2        padding: const EdgeInsets.only(right:    color: theme.colorScheme.error,
          borderRadius: BorderRadius.ci          borderRadius: BorderRadius.ci          borderRadius: BorderRadius.ci          borderRadius: BorderRadius.ci          borderRadius: BorderRadius.ci          borderRadius: BorderRadius.ci          borderRadius: BorderRadius.ci          borderRadius: Borderconst EdgeInsets.all(20),
            child: Column(
              cros              cros              cros              cros            [
                                       crossAxisAlignment: CrossAxisAlignment.sta                       hildren: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            pitch.name,
                            style: theme.textTheme.titleLarge?.copyWith(
                              fontWeight: FontWeight.w700,
                            ),
                            maxLines: 1,
                                                                                                                                                                                                                                                                                                                                                                             rScheme.onSurfaceVariant,
                            ),
                          ),
                                                                        ),
                    Icon(
                      Icons.chevron_right_rounded,
                      color: theme.colo                      color: theme.colo                      color:           ),
                  ],
                                   c          Box(height: 16),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(
                    color: isCalibrated
                                                                                                                                                                                                                                                                                                                                                                                                                         ted                           ns.w                                              size: 16,
                        color: isCalibrated ? theme.colorScheme.tertiary : theme.colorScheme.error,
                      ),
                      ),
olor: isCalibrated ? theme.colorScheme.tertiary : theme.colorScheme.error,
           d ? 'Calibrated & Ready' : 'Needs Calibration',
                        style: theme.textTheme.labelMedium?.copyWith(
                          color: isCalibrated ? theme.colorScheme.tertiary : theme.col                          color: is       fontWeight: FontWeight.w700,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               4)                                                                                                 diu                       r(                        c                                                                                                                                    ias,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              pitch.name,
                              style: theme.textTheme.headlineSmall?.copyWith(
                                fontWeight: FontWeight.w700,
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(
                        'Updated ${_formatDate(pitch.updatedAt)}',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                      const SizedBox(height: 16),
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Container(
                            width: 8,
                            height: 8,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              color: isCalibrated ? theme.colorScheme.tertiary : theme.colorScheme.error,
                            ),
                          ),
                          const SizedBox(width: 8),
                          Text(
                            isCalibrated ? 'Ready' : 'Needs Calibration',
                            style: theme.textTheme.labelMedium?.copyWith(
                              color: isCalibrated ? theme.colorScheme.tertiary : theme.colorScheme.error,
                                                                                    ],
                      ),
                    ],
                  ),
                ),
                Icon(
                  Icons.arrow_forward_ios_rounded,
                  color: theme.colorScheme.onSurfaceVariant.withValues(alpha: 0.5),
                  size: 20,
                ),
              ],
            ),
          ),
        ),
      ),
    );
"""

import sys
text = text.replace(card_old.strip(), card_new.strip())

with open('app/pocket_drs/lib/src/screens/pitches_screen.dart', 'w') as f:
    f.write(text)

