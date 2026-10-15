"""Data preservation and state guard checks for the shipped SQL migration."""
import sqlite3
from pathlib import Path

import pytest
from sql_harness import Clock, connect, initialize, create, consent_phase, approve, claim
from smtp_worker import process

ROOT=Path(__file__).resolve().parents[1]


def test_version_one_upgrade_preserves_requests_grants_and_mail_limits(tmp_path):
    clock=Clock()
    db=connect(tmp_path/'state.db',clock)
    # Build a populated version-one fixture with the actual old migration.
    initialize(db, existing_login=False)
    create(db,clock)
    consent_phase(db)
    approve(db,clock)
    claim(db)
    db.execute("INSERT INTO mail_blocks VALUES('recipient-hash',?)",(clock.now,))
    db.execute("INSERT INTO rate_events(bucket,occurred_at) VALUES('destination',?)",(clock.now,))
    tables=('accounts','requests','grants','sessions','audit','mail_blocks','rate_events')
    before={table:[tuple(row) for row in db.execute(f'SELECT * FROM {table}')] for table in tables}
    assert db.execute('PRAGMA user_version').fetchone()[0]==1
    db.executescript((ROOT/'migrations/0002_existing_login.sql').read_text())
    assert db.execute('PRAGMA user_version').fetchone()[0]==2
    assert before=={table:[tuple(row) for row in db.execute(f'SELECT * FROM {table}')] for table in tables}
    create(db,clock,'r2')
    db.execute("UPDATE requests SET phase='awaiting_consent',status_updated_at=hg_now() WHERE id='r2'")
    assert claim(db,'r2')==0  # Entering confirmation still issues no credential.
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE requests SET actor_id='other' WHERE id='r2'")
    db.close()


@pytest.mark.parametrize('version',[1,2])
def test_mail_worker_accepts_both_non_destructive_schema_versions(tmp_path,version):
    path=tmp_path/'state.db'
    clock=Clock()
    db=connect(path,clock)
    initialize(db,existing_login=version==2)
    db.close()
    assert process(path,lambda _:pytest.fail('No mail is queued'),clock=lambda:clock.now)==[]
