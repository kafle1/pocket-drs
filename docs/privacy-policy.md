# Pocket DRS privacy policy

Last updated: 26 September 2026

Pocket DRS has no accounts, no ads, and no analytics. It doesn't ask for your name, email, or
location.

## What leaves your phone

When you send a ball, the app sends two things to the analysis server:

- the video, without sound. In a session that is the last 4 seconds. With Analyse a video it
  is only the part you trimmed to, plus a little before it (usually under two seconds) so the video
  opens cleanly.
- the eight stump marks you tapped, the batter's handedness, and the pitch length

The server deletes the video as soon as it has finished analysing it. The result it keeps is
numbers only: where the ball went, the verdict, the speed. Results are deleted once they are more
than a day old. The cleanup runs whenever the next ball is sent in.

The server writes a log line for each request. It holds only the time and the page asked for,
never your network address or the video. The
default server is a computer at the developer's home, reached through Tailscale Funnel. Tailscale
passes the encrypted connection through without being able to read it, but like any relay it
sees your network address.

The 3D view opens in your web browser and loads its drawing code from unpkg.com, so that site
also sees your network address when you open it. Nothing about the ball is sent there.

## What stays on your phone

- Clips recorded in a session sit in the app's temporary folder and are deleted when you leave the session.
- A clip filmed with Record video in Analyse a video stays in the app's folder. Turn on Settings >
  Storage > Delete recordings after analysis to remove it once you leave the result.
- Your theme, speed unit (km/h or mph) and pitch length are saved on the phone.
- The app keeps a small error log on the phone. It is never sent anywhere.

## Permissions

- **Camera**: to record the deliveries, in a session or with Record video. Nothing is recorded
  at any other time.
- **Photos and videos**: only when you pick a clip with Analyse a video, through the phone's own
  picker. The app sees only the clip you pick.
- **Internet**: to send the clip to the server and get the verdict back.

The app doesn't use the microphone.

## Children

Pocket DRS doesn't knowingly collect anything from anyone, children included, beyond what is
listed above.

## Changes and contact

If this policy changes, the new version goes in this file with a new date. Questions go to
contact.me.kafle@gmail.com.
