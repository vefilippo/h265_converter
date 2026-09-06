"""Pins the conditional commit in the app lifespan:

    if migrate_encoder_family(_db) is not None:
        _db.commit()

`seed_settings_from_env` commits unconditionally a few lines later, so on a
fresh install today the migration's row survives even if its own commit is
deleted -- it just rides in on the seeder's commit. That's an accident of
ordering, not a guarantee: the moment the seeder is reordered or made
conditional, an uncommitted migration would be silently lost. This test pins
the actual invariant -- the migration's write is durable (committed) *before*
the seeder ever runs -- by recording the relative order of "the commit that
follows migrate_encoder_family" and "the seeder call".

Both `migrate_encoder_family` and `seed_settings_from_env` are imported with a
function-local `from ... import ...` inside app.py's lifespan closure, so
there is no module-level `app_module.seed_settings_from_env` attribute to
patch (unlike the plan's sketch). Each lifespan run re-executes those import
statements, which bind to whatever the *source* module's attribute currently
is -- so patching `transcoder.repo.seed_settings_from_env` and
`transcoder.encoders.migrate_encoder_family` is what actually takes effect.
"""

from tests.api_conftest import build_booted_client


def test_encoder_family_is_committed_before_the_seeder_runs(monkeypatch):
    """If the migration's own commit is removed, the family row rides on the
    seeder's commit -- fine today, silently broken the moment the seeder is
    reordered or made conditional."""
    order = []

    import transcoder.repo as repo_module
    real_seed = repo_module.seed_settings_from_env

    def spy_seed(db, mapping):
        order.append("seed")
        return real_seed(db, mapping)

    monkeypatch.setattr(repo_module, "seed_settings_from_env", spy_seed)

    import transcoder.encoders as enc
    real_migrate = enc.migrate_encoder_family

    def spy_migrate(session):
        value = real_migrate(session)
        original_commit = session.commit

        def tracking_commit():
            order.append("commit-after-migrate")
            session.commit = original_commit
            return original_commit()

        session.commit = tracking_commit
        return value

    monkeypatch.setattr(enc, "migrate_encoder_family", spy_migrate)

    client, _Session = build_booted_client(monkeypatch)
    with client:
        pass

    assert order == ["commit-after-migrate", "seed"]
