from sqlalchemy import create_engine, text


def test_ensure_job_columns_adds_missing_and_copies_log_excerpt():
    from transcoder.db import ensure_job_columns
    eng = create_engine("sqlite://")
    with eng.begin() as conn:
        # Simulate an OLD schema: job with log_excerpt, no phase/log.
        conn.execute(text(
            "CREATE TABLE job (id INTEGER PRIMARY KEY, state VARCHAR, "
            "log_excerpt TEXT)"
        ))
        conn.execute(text(
            "INSERT INTO job (id, state, log_excerpt) VALUES (1, 'done', 'old line')"
        ))

    ensure_job_columns(eng)

    with eng.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(job)"))}
        assert "phase" in cols and "log" in cols
        row = conn.execute(text("SELECT log FROM job WHERE id=1")).one()
        assert row[0] == "old line"

    # Idempotent: a second call must not raise.
    ensure_job_columns(eng)
