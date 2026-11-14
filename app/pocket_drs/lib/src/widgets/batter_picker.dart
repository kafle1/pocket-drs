import 'package:flutter/material.dart';

/// Which way the batter stands, since leg and off swap sides for a left-hander.
class BatterPicker extends StatelessWidget {
  const BatterPicker({super.key, required this.hand, required this.onChanged});
  final String hand;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return SegmentedButton<String>(
      expandedInsets: EdgeInsets.zero,
      // the tick pushes "Right-handed" past its half on a 320 wide phone
      showSelectedIcon: false,
      segments: const [
        ButtonSegment(value: 'right', label: Text('Right-handed')),
        ButtonSegment(value: 'left', label: Text('Left-handed')),
      ],
      selected: {hand},
      onSelectionChanged: (s) => onChanged(s.first),
    );
  }
}
