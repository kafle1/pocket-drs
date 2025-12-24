from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("POCKET_DRS_HOST", "0.0.0.0")
    port = int(os.environ.get("POCKET_DRS_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
