# PocketDRS — Install & Run on a Real Phone

This guide walks you through running PocketDRS end-to-end with a real phone
recording / replaying cricket footage against a backend running on your
laptop on the same Wi-Fi.

The session has already produced a debug APK at
`app/pocket_drs/build/app/outputs/flutter-apk/app-debug.apk`
with `POCKET_DRS_SERVER_URL=http://192.168.1.84:8000` baked in.

If your laptop's LAN address differs you can override it at runtime from the
Settings screen, or rebuild the APK with the right `--dart-define`.

---

## 1. Start the backend on your laptop

```bash
cd /Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs/server
.venv/bin/python run.py
```

Wait for "Application startup complete." then probe:

```bash
curl http://localhost:8000/healthz
# → {"status":"ok"}
```

The server binds to `0.0.0.0:8000` so any device on the same LAN can reach
`http://<laptop-ip>:8000`. Find your laptop's address with:

```bash
python3 scripts/detect_host_ip.py
# → e.g. 192.168.1.84
```

---

## 2. Make sure your phone and laptop are on the same Wi-Fi

The default Android emulator address `10.0.2.2` only works inside an Android
emulator. A **real phone** must use the laptop's LAN IP (`192.168.1.84` in
the prebuilt APK).

---

## 3. Install the APK on Android

### Option A — sideload via adb (USB cable + USB debugging enabled)

```bash
adb devices                       # confirm phone shows up
adb install -r app/pocket_drs/build/app/outputs/flutter-apk/app-debug.apk
```

### Option B — transfer the APK manually

1. Copy `app-debug.apk` to the phone (AirDrop / Google Drive / cable).
2. On the phone, open the file. Allow "Install from unknown sources" when
   prompted.
3. Tap **Install**.

The app icon will be **pocket_drs**.

### Option C — rebuild with your own LAN IP

```bash
cd /Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs/app/pocket_drs
flutter build apk --debug \
  --dart-define=POCKET_DRS_SERVER_URL=http://<YOUR_LAN_IP>:8000
adb install -r build/app/outputs/flutter-apk/app-debug.apk
```

---

## 4. iOS install (Xcode required)

```bash
cd app/pocket_drs
open ios/Runner.xcworkspace
# Xcode → select your iPhone as the target → Run
```

Trust the developer certificate on the iPhone (Settings → General → VPN &
Device Management) the first time.

---

## 5. First-run flow on the phone

1. **Sign in** with the email/password account you configured in Firebase
   (this is the same Firebase project as the dev backend).
2. The home shell will probe the server. If unreachable a snackbar pops up
   with a *Set Server URL* action — tap it and enter `http://<laptop-ip>:8000`.
3. **Pitches → Add pitch**. Tap the four pitch corners on a calibration
   photo (striker-left, striker-right, bowler-right, bowler-left in order).
   Optional: also tap the stump bases at both ends. Save.
4. **Open the pitch → Add delivery**.
5. **Record** or **Choose file**: pick the delivery video. Trim the segment
   that contains the ball flight.
6. Tap **Analyze Delivery**. The phone uploads the video; the server runs
   the full pipeline (decode → calibration → tracking → reconstruction →
   LBW). Progress updates roll in over 5–30 seconds.
7. When processing finishes, the 3D Hawk-Eye viewer renders the trajectory
   with the LBW decision banner. Drag to orbit, pinch to zoom.

---

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| "Cannot reach server" | Confirm laptop and phone are on the same Wi-Fi; check the Settings → Server URL value matches `python3 scripts/detect_host_ip.py`; try `curl http://<ip>:8000/healthz` from another device on the same LAN. |
| "Please sign in again" | Firebase token expired — open the app, sign out, sign back in. |
| "Failed to load video" | The phone's image picker may have returned a cloud-only URL. Re-record locally or download the file fully first. |
| Analysis returns "No 3D trajectory" | The pitch corners were imprecise or the ball wasn't visible enough. Re-calibrate, ensure the red ball stands out from the pitch / background, retry with a clearer clip. |
| 3D viewer stuck on "Loading" | A WebView resource failed (this is logged via the bridge). Restart the app. |

---

## 7. Validating without a phone (web build)

```bash
cd app/pocket_drs
flutter build web --no-tree-shake-icons
cd build/web && python3 -m http.server 5173 &

# In another terminal:
cd ../../../server && .venv/bin/python run.py
```

Browse to `http://localhost:5173`. The web build hits
`http://localhost:8000` by default (override via `Settings → Server URL`).

---

## 8. Re-running the synthetic and real-video validation harnesses

```bash
cd server && PYTHONPATH=. .venv/bin/python scripts/synth_validate.py
cd server && PYTHONPATH=. .venv/bin/python scripts/realvideo_validate.py
```

Outputs land in `dump/validation/`.
