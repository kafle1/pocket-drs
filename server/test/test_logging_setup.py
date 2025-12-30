from __future__ import annotations

import logging


def _flush_all_handlers() -> None:
    # dictConfig installs handlers on the root logger.
    root = logging.getLogger()
    for h in list(root.handlers):
        try:
            h.flush()
        except Exception:
            pass


def test_configure_logging_writes_to_server_log(tmp_path, monkeypatch):
    monkeypatch.setenv("POCKET_DRS_LOG_ROOT", str(tmp_path))

    from app.logging_setup import configure_logging

    configure_logging(log_level="info")

    log = logging.getLogger("pocket_drs")
    log.info("hello-from-test")

    _flush_all_handlers()

    p = tmp_path / "server" / "server.log"
    assert p.exists()
    assert "hello-from-test" in p.read_text(encoding="utf-8")


def test_job_log_context_writes_central_job_log(tmp_path, monkeypatch):
    monkeypatch.setenv("POCKET_DRS_LOG_ROOT", str(tmp_path))

    from app.logging_setup import configure_logging
    from app.job_logging import job_log_context

    configure_logging(log_level="info")

    artifacts_dir = tmp_path / "artifacts"
    with job_log_context(job_id="job123", artifacts_dir=artifacts_dir) as job_log:
        job_log.info("job-log-line")

    _flush_all_handlers()

    central = tmp_path / "server" / "jobs" / "job123.log"
    assert central.exists()
    assert "job=job123" in central.read_text(encoding="utf-8")
    assert "job-log-line" in central.read_text(encoding="utf-8")

    per_job = artifacts_dir / "server.log"
    assert per_job.exists()
    assert "job-log-line" in per_job.read_text(encoding="utf-8")
