"""Pytest configuration.

This repository has a top-level `app/` directory for the Flutter client.
The Python backend also historically uses an `app` package (located at
`server/app`).

When pytest chooses the repository root as its `rootdir`, imports like
`import app.pipeline...` can accidentally resolve against the Flutter `app/`
folder (which is not a Python package) and fail.

To keep the backend tests stable, ensure `server/` is at the front of
`sys.path` so `import app` refers to `server/app`.
"""

from __future__ import annotations

import sys
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
