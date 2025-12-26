import 'package:flutter/material.dart';

/// Web fallback for the camera recording screen.
///
/// We keep this separate so Flutter Web builds don't pull in mobile-only
/// camera/permission dependencies.
class CameraRecordScreen extends StatelessWidget {
  const CameraRecordScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Record delivery')),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('Camera recording is not supported on Web in this build.', style: theme.textTheme.titleLarge),
              const SizedBox(height: 8),
              const Text('Please use “Import video” instead.'),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: () => Navigator.of(context).pop(null),
                child: const Text('Back'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
