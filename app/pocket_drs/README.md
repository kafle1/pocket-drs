# Pocket DRS - Flutter App

Mobile application for phone-based Hawk-Eye-style LBW Decision Review System.

## Features

- **Live camera capture** at 60-120 FPS
- **Calibration interface** for pitch landmark selection
- **Video playback** with ball tracking overlay
- **LBW decision display** with ICC Rule 36 compliance
- **3D trajectory visualization** (Three.js integration)

## Setup

```bash
flutter pub get
flutter run
```

## Camera Requirements

- **FPS**: Minimum 60 FPS, ideal 120 FPS
- **Position**: Side-on view at square of wicket
- **Height**: 1.2-1.5m from ground
- **Distance**: 8-12m from pitch
- **Settings**: Locked focus, locked exposure

## Backend Integration

The app communicates with the Python backend API:

```
POST /api/process-job
GET /api/job/{job_id}/status
GET /api/job/{job_id}/result
```

Configure backend URL in app settings.

## Architecture

```
lib/
├── main.dart              # App entry point
└── src/
    ├── api/              # Backend API integration
    ├── calibration/      # Camera calibration UI
    ├── recording/        # Video capture
    ├── playback/         # Video playback + overlay
    └── visualization/    # 3D trajectory display
```

## Development

See main project [README](../../README.md) for complete system documentation.
