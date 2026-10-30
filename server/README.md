The analysis server behind the Pocket DRS app. It takes a phone clip of one delivery and returns
the ball path, speed and the LBW call.

Get the app and the source at https://github.com/kafle1/pocket-drs

## Hosting

The public server is https://pocketdrs-saarathi.centralindia.cloudapp.azure.com, an Azure VM in
Central India. Caddy on the VM handles HTTPS and passes requests to a Docker container named
`pocket-drs`, which listens on 127.0.0.1:7860. The host folder `/opt/pocket-drs-data` is mounted at
`/data` and holds the SQLite database (`pocketdrs.db`) and `firebase-web.json`, so both survive a
rebuild. Uploaded clips and job results live inside the container and go when it is replaced.

To ship a change, run `make deploy` from the repo root. It copies `server/` to the VM, rebuilds the
image, restarts the container and waits for `/healthz` to answer.

## Environment variables

| Variable | Default | What it does |
|---|---|---|
| `ADMIN_EMAILS` | `kafleniraj@gmail.com` | Comma-separated emails that get admin rights and unlimited reviews |
| `POCKET_DRS_DB` | `/data/pocketdrs.db` | SQLite file for accounts, devices and review counts |
| `FIREBASE_WEB_CONFIG` | `/data/firebase-web.json` | Firebase web config served at `/config.json` for the browser app |
| `FIREBASE_MEASUREMENT_ID` | unset | Overrides the Google Analytics measurement id in that config |
| `POCKET_DRS_DATA_DIR` | `/app/data` in the image | Where job folders (clip, status, result) are written |
| `POCKET_DRS_LOG_LEVEL` | `info` | Log level |

`run.py`, which `make dev` uses on your own machine, also reads `POCKET_DRS_HOST` (default
`0.0.0.0`), `POCKET_DRS_PORT` (default `8000`) and `POCKET_DRS_RELOAD` (default `0`).
