The analysis server behind the Pocket DRS app. It takes a phone clip of one delivery and returns
the ball path, speed and the LBW call.

Get the app and the source at https://github.com/kafle1/pocket-drs

To host it on a Mac, run `brew install tailscale`, then `make host` from the repo root. The server
and Tailscale then start at every login, with the server on port 7860. Tailscale runs without
admin rights here, so its commands need the socket path. Once, log in and put the port online:

    tailscale --socket ~/.pocket-drs/tailscaled.sock up --hostname=pocket-drs
    tailscale --socket ~/.pocket-drs/tailscaled.sock funnel --bg 7860

Then turn off key expiry for that Mac in the Tailscale admin page, or the public address stops
working after 180 days. In this mode Tailscale passes connections from your other devices on to
any port on the Mac, so keep that tailnet to devices you own.
