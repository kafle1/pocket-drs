The analysis server behind the Pocket DRS app. It takes a phone clip of one delivery and returns
the ball path, speed and the LBW call.

Get the app and the source at https://github.com/kafle1/pocket-drs

## Hosting

The public server is https://pocketdrs-saarathi.centralindia.cloudapp.azure.com, an Azure VM in
Central India. Caddy on the VM handles HTTPS and passes requests to a Docker container named
`pocket-drs`, which listens on 127.0.0.1:7860. The host folder `/opt/pocket-drs-data` is mounted at
`/data` and holds the SQLite database (`pocketdrs.db`), `firebase-web.json` and the job folders, so
all of them survive a rebuild. Clips go as soon as their check ends; results go after a day.

The website itself is published to https://pocket-drs-app.web.app by Firebase Hosting, from the same
`server/app/web` folder (`hosting/web` links to it), and talks to this server for everything else.
`make deploy` updates both. The server still serves the same page at its own address.

To ship a change, run `make deploy` from the repo root. It copies `server/` to the VM, rebuilds the
image, waits up to 10 minutes (`DRAIN_WAIT_S`) for running reviews to finish, restarts the
container and waits for `/healthz` to answer.

## Environment variables

| Variable | Default | What it does |
|---|---|---|
| `ADMIN_EMAILS` | none | Comma-separated emails that get admin rights and unlimited reviews |
| `POCKET_DRS_DB` | `pocketdrs.db` in the data folder | SQLite file for accounts and the last day's reviews; a copy goes to `backups/` next to it every night and the last 7 are kept |
| `FIREBASE_WEB_CONFIG` | `firebase-web.json` in the data folder | Firebase web config served at `/config.json` for the browser app |
| `POCKET_DRS_DATA_DIR` | `/data` in the image, the repo's `data/` otherwise | The data folder: job folders (clip, status, result), and by default the database and web config |
| `POCKET_DRS_LOG_LEVEL` | `info` | Log level |

`make server` runs it on your own machine at port 8000.
