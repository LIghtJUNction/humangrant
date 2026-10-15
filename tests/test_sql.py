"""Security invariants of shipped SQLite statements; these do not certify the Rust HTTP adapter."""
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sql_harness import Clock, ROOT, approve, claim, connect, consent_phase, create, effective, enqueue, initialize, mail_allowed, sql


@pytest.fixture
def database(tmp_path):
    clock = Clock()
    path = tmp_path / "database.db"
    db = connect(path, clock)
    initialize(db)
    yield db, clock, path
    db.close()


def ready(database):
    db, clock, _ = database
    create(db, clock)
    consent_phase(db)
    approve(db, clock)
    assert claim(db) == 1
    return db, clock


def test_read_only_grant_is_an_exact_resource_pair(database):
    db, _ = ready(database)
    assert effective(db) == {("notes.read", "alice-note")}
    assert ("notes.write", "alice-note") not in effective(db)
    assert ("notes.read", "alice-other-note") not in effective(db)
    assert ("notes.read", "bob-note") not in effective(db)


@pytest.mark.parametrize("actor,token,service", [
    ("wrong-agent", "restricted-test-token", "notes"),
    ("agent-A", "link-r1", "notes"),
    ("agent-A", "restricted-test-token", "other-service"),
    ("agent-A", "unknown-token", "notes"),
])
def test_session_is_bound_to_actor_token_and_service(database, actor, token, service):
    db, _ = ready(database)
    assert not effective(db, actor, token, service)


@pytest.mark.parametrize("phase", ["waiting_human", "authenticating_human", "awaiting_consent"])
def test_authentication_without_consent_issues_no_session(database, phase):
    db, clock, _ = database
    create(db, clock)
    if phase != "waiting_human":
        db.execute("UPDATE requests SET phase='authenticating_human',status_updated_at=hg_now()")
    if phase == "awaiting_consent":
        db.execute("UPDATE requests SET phase='awaiting_consent',status_updated_at=hg_now()")
    assert claim(db) == 0
    assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


@pytest.mark.parametrize("permissions", [
    [{"action": "administrator", "resource": "alice-note"}],
    [{"action": "notes.read", "resource": "alice-other-note"}],
    [{"action": "notes.read", "resource": "bob-note"}],
    [{"action": "notes.read", "resource": "*"}],
    [{"action": "notes.read", "resource": "alice-note"}, {"action": "notes.read", "resource": "alice-note"}],
    [],
])
def test_unrequested_unknown_or_empty_permissions_are_denied(database, permissions):
    db, clock, _ = database
    create(db, clock)
    consent_phase(db)
    with pytest.raises(sqlite3.IntegrityError):
        approve(db, clock, permissions=permissions)
    assert db.execute("SELECT count(*) FROM grants").fetchone()[0] == 0


def test_requesting_someone_elses_resource_does_not_make_it_grantable(database):
    db, clock, _ = database
    pairs = [{"action": "notes.read", "resource": "bob-note"}]
    create(db, clock, permissions=pairs)
    consent_phase(db)
    with pytest.raises(sqlite3.IntegrityError):
        approve(db, clock, human="alice", permissions=pairs)
    approve(db, clock, human="bob", permissions=pairs)
    claim(db)
    assert effective(db) == {("notes.read", "bob-note")}


def test_expected_human_restriction(database):
    db, clock, _ = database
    pairs = [{"action": "notes.read", "resource": "bob-note"}]
    create(db, clock, expected="alice", permissions=pairs)
    consent_phase(db)
    with pytest.raises(sqlite3.IntegrityError, match="binding"):
        approve(db, clock, human="bob", permissions=pairs)


@pytest.mark.parametrize("field,value", [
    ("actor_id", "other-agent"), ("actor_public_key", "other-key"), ("client_id", "other-client"),
    ("target_service", "other-service"), ("purpose", "changed instruction"),
    ("permissions", '[]'), ("expected_human_id", "bob"), ("human_link", "new-link"),
    ("expires_at", 1_800_000_000), ("requested_grant_expires_at", 1_800_000_000),
    ("audit_id", "other-audit"),
])
def test_request_binding_cannot_be_changed(database, field, value):
    db, clock, _ = database
    create(db, clock)
    consent_phase(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(f"UPDATE requests SET {field}=? WHERE id='r1'", (value,))


@pytest.mark.parametrize("target", ["approved", "succeeded"])
def test_cannot_skip_state_transitions(database, target):
    db, clock, _ = database
    create(db, clock)
    with pytest.raises(sqlite3.IntegrityError, match="transition"):
        db.execute("UPDATE requests SET phase=?,status_updated_at=hg_now()", (target,))


@pytest.mark.parametrize("ending", ["rejected", "cancelled", "expired"])
def test_terminal_requests_cannot_be_resumed(database, ending):
    db, clock, _ = database
    create(db, clock)
    db.execute("UPDATE requests SET phase=?,status_updated_at=hg_now()", (ending,))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE requests SET phase='authenticating_human',status_updated_at=hg_now()")
    assert claim(db) == 0


def test_approval_and_claim_are_one_time(database):
    db, clock, _ = database
    create(db, clock)
    consent_phase(db)
    approve(db, clock)
    with pytest.raises(sqlite3.IntegrityError):
        approve(db, clock)
    assert claim(db, actor="wrong-agent") == 0
    assert claim(db) == 1
    with pytest.raises(sqlite3.IntegrityError):
        sql(db, "claim", {"id": "different-session", "request": "r1", "actor": "agent-A", "token_hash": "different-token-hash"})
    assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


def test_nonce_replay_reservation_survives_connection_restart(database):
    db, clock, path = database
    db.execute("INSERT INTO nonces VALUES('agent-A','random-nonce',?)", (clock.now + 60,))
    again = connect(path, clock)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            again.execute("INSERT INTO nonces VALUES('agent-A','random-nonce',?)", (clock.now + 60,))
    finally:
        again.close()


def test_checked_time_does_not_update_state_timestamp(database):
    db, clock, _ = database
    create(db, clock)
    original = db.execute("SELECT status_updated_at FROM requests").fetchone()[0]
    clock.advance(5)
    db.execute("UPDATE requests SET next_poll_at=?,poll_interval=10", (clock.now + 10,))
    assert clock.now > original
    assert db.execute("SELECT status_updated_at FROM requests").fetchone()[0] == original
    with pytest.raises(sqlite3.IntegrityError, match="timestamp"):
        db.execute("UPDATE requests SET status_updated_at=hg_now()")
    db.execute("UPDATE requests SET phase='authenticating_human',status_updated_at=hg_now()")
    assert db.execute("SELECT status_updated_at FROM requests").fetchone()[0] == clock.now


@pytest.mark.parametrize("offset", [0, -1, 3601])
def test_grant_expiration_can_only_shrink(database, offset):
    db, clock, _ = database
    create(db, clock)
    consent_phase(db)
    with pytest.raises(sqlite3.IntegrityError):
        approve(db, clock, expires=clock.now + offset)


def test_approval_ordered_after_expiry_fails(database):
    db, clock, _ = database
    create(db, clock)
    consent_phase(db)
    clock.advance(600)
    with pytest.raises(sqlite3.IntegrityError):
        approve(db, clock)
    db.executescript((ROOT / "src/sql/expire.sql").read_text())
    assert db.execute("SELECT phase FROM requests").fetchone()[0] == "expired"


def test_approval_before_expiry_does_not_allow_claim_after_expiry(database):
    db, clock, _ = database
    create(db, clock)
    consent_phase(db)
    clock.advance(599)
    approve(db, clock)
    clock.advance()
    with pytest.raises(sqlite3.IntegrityError):
        claim(db)


def test_revocation_does_not_rewrite_historical_success(database):
    db, clock = ready(database)
    clock.advance()
    db.execute("UPDATE grants SET revoked_at=hg_now()")
    assert not effective(db)
    assert db.execute("SELECT phase FROM requests").fetchone()[0] == "succeeded"
    assert db.execute("SELECT revoked_at FROM grants").fetchone()[0] == clock.now
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE grants SET revoked_at=NULL")


def test_revoke_before_claim_cancels_unfinished_request(database):
    db, clock, _ = database
    create(db, clock)
    consent_phase(db)
    approve(db, clock)
    db.execute("UPDATE grants SET revoked_at=hg_now()")
    assert db.execute("SELECT phase FROM requests").fetchone()[0] == "cancelled"
    with pytest.raises(sqlite3.IntegrityError):
        claim(db)


@pytest.mark.parametrize("change", [
    "DELETE FROM entitlements WHERE account_id='alice' AND action='notes.read'",
    "UPDATE accounts SET enabled=0 WHERE id='alice'",
    "UPDATE resources SET owner_id='bob' WHERE id='alice-note'",
])
def test_current_parent_rights_and_ownership_are_checked_on_each_access(database, change):
    db, _ = ready(database)
    assert effective(db)
    db.execute(change)
    assert not effective(db)


def test_current_service_policy_is_checked(database):
    db, _ = ready(database)
    db.execute("DELETE FROM entitlements WHERE action='notes.read'")
    db.execute("DELETE FROM service_policy WHERE action='notes.read'")
    assert not effective(db)


def test_session_expires_without_rewriting_success(database):
    db, clock = ready(database)
    clock.advance(1800)
    assert not effective(db)
    db.executescript((ROOT / "src/sql/expire.sql").read_text())
    assert db.execute("SELECT phase FROM requests").fetchone()[0] == "succeeded"


def test_concurrent_claims_create_exactly_one_session(database):
    db, clock, path = database
    create(db, clock)
    consent_phase(db)
    approve(db, clock)
    barrier = threading.Barrier(2)
    def compete(number):
        local = connect(path, clock)
        try:
            barrier.wait(timeout=5)
            local.execute("BEGIN IMMEDIATE")
            sql(local, "claim", {"id": "s"+str(number), "request":"r1", "actor":"agent-A", "token_hash":"hash"+str(number)})
            local.commit()
            return True
        except sqlite3.IntegrityError:
            local.rollback()
            return False
        finally:
            local.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, (1, 2)))
    assert sum(results) == 1
    assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


def test_access_ordered_after_concurrent_revocation_is_denied(database):
    db, clock = ready(database)
    path = database[2]
    acquired, waiting = threading.Event(), threading.Event()
    def revoker():
        local = connect(path, clock)
        try:
            local.execute("BEGIN IMMEDIATE")
            local.execute("UPDATE grants SET revoked_at=hg_now()")
            acquired.set()
            assert waiting.wait(5)
            local.commit()
        finally:
            local.close()
    def accessor():
        assert acquired.wait(5)
        local = connect(path, clock)
        try:
            waiting.set()
            local.execute("BEGIN IMMEDIATE")
            result = effective(local)
            local.commit()
            return result
        finally:
            local.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        revoke_future = pool.submit(revoker)
        access_future = pool.submit(accessor)
        revoke_future.result(10)
        assert not access_future.result(10)


def test_approve_waiting_for_lock_observes_expiry(database):
    db, clock, path = database
    create(db, clock)
    consent_phase(db)
    db.execute("BEGIN IMMEDIATE")
    started = threading.Event()
    def approver():
        local = connect(path, clock)
        try:
            started.set()
            local.execute("BEGIN IMMEDIATE")
            approve(local, clock)
            local.commit()
            return True
        except sqlite3.IntegrityError:
            local.rollback()
            return False
        finally:
            local.close()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(approver)
        assert started.wait(5)
        clock.advance(600)
        db.commit()
        assert not future.result(10)


def test_email_cooldown_is_cross_request_and_persistent(database):
    db, clock, path = database
    create(db, clock)
    create(db, clock, "r2")
    assert mail_allowed(db)
    enqueue(db)
    assert not mail_allowed(db)
    again = connect(path, clock)
    try:
        assert not mail_allowed(again)
        clock.advance(59)
        assert not mail_allowed(again)
        clock.advance()
        assert mail_allowed(again)
        enqueue(again, "r2", "op2")
    finally:
        again.close()
    assert not mail_allowed(db)


def test_email_recipient_hour_and_day_limits(database):
    db, clock, _ = database
    create(db, clock)
    for number in range(3):
        assert mail_allowed(db)
        enqueue(db, operation=f"op{number}")
        clock.advance(60)
    assert not mail_allowed(db)
    clock.advance(3600)
    for number in range(3,5):
        assert mail_allowed(db)
        enqueue(db, operation=f"op{number}")
        clock.advance(60)
    clock.advance(3600)
    assert not mail_allowed(db)


@pytest.mark.parametrize("limit_name,limit", [("actor_hour",10),("source_hour",10),("service_hour",3),("service_day",3)])
def test_actor_source_and_service_mail_limits(database, limit_name, limit):
    db, clock, _ = database
    create(db, clock)
    limits={"recipient_hour":100,"recipient_day":100,"actor_hour":100,"source_hour":100,"service_hour":100,"service_day":100,limit_name:limit}
    for number in range(limit):
        recipient=f"recipient-{number}"
        assert mail_allowed(db,recipient=recipient,**limits)
        enqueue(db,operation=f"op{number}",recipient=recipient)
    assert not mail_allowed(db,recipient="new-mailbox",**limits)


def test_mail_operation_is_idempotently_reserved(database):
    db, clock, _ = database
    create(db, clock)
    enqueue(db,operation="op1",key="same-operation")
    with pytest.raises(sqlite3.IntegrityError):
        enqueue(db,operation="op2",key="same-operation")
    assert db.execute("SELECT count(*) FROM mail_operations").fetchone()[0] == 1


@pytest.mark.parametrize("state", ["failed","delivery_unknown","transport_accepted","local_spooled"])
def test_failed_or_ambiguous_mail_does_not_release_reserved_cooldown(database,state):
    db, clock, _ = database
    create(db, clock)
    enqueue(db,state=state)
    assert not mail_allowed(db)


def test_email_block_applies_to_new_agent_keys(database):
    db, clock, _ = database
    create(db, clock)
    db.execute("INSERT INTO mail_blocks VALUES('mail-hash',hg_now())")
    assert not mail_allowed(db,actor="new-agent-key",source="different-source")


def test_pending_expired_email_is_not_queued_for_delivery(database):
    db, clock, _ = database
    create(db, clock)
    enqueue(db)
    clock.advance(600)
    db.executescript((ROOT / "src/sql/expire.sql").read_text())
    assert db.execute("SELECT state FROM mail_operations").fetchone()[0] == "expired"


def test_resend_does_not_extend_request(database):
    db, clock, _ = database
    create(db, clock)
    expires=db.execute("SELECT expires_at FROM requests").fetchone()[0]
    enqueue(db)
    clock.advance(60)
    enqueue(db,operation="second-operation")
    assert db.execute("SELECT expires_at FROM requests").fetchone()[0] == expires


def test_concurrent_recipient_reservations_cannot_bypass_cooldown(database):
    db, clock, path = database
    create(db, clock)
    barrier=threading.Barrier(4)
    def reserve(number):
        local=connect(path,clock)
        try:
            barrier.wait(timeout=5)
            local.execute("BEGIN IMMEDIATE")
            allowed=mail_allowed(local)
            enqueue(local,operation=f"concurrent-{number}",state="queued" if allowed else "suppressed")
            local.commit()
            return allowed
        finally:
            local.close()
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve,range(4))) == 1
    assert db.execute("SELECT count(*) FROM mail_operations WHERE state='queued'").fetchone()[0] == 1


def test_audit_has_events_not_credentials_or_mail_addresses(database):
    db, _ = ready(database)
    serialized=json.dumps([dict(row) for row in db.execute("SELECT * FROM audit")])
    for secret in ("restricted-test-token", "alice secret", "recipient@example.test", "link-r1"):
        assert secret not in serialized
    assert "grant_approved" in serialized and "succeeded" in serialized


def test_current_client_service_binding_is_rechecked(tmp_path):
    from sql_harness import Clock, connect, initialize, create, consent_phase, approve, claim, effective
    clock = Clock()
    db = connect(tmp_path / "client-policy.db", clock)
    initialize(db)
    create(db, clock)
    consent_phase(db)
    approve(db, clock)
    claim(db)
    assert effective(db) == {("notes.read", "alice-note")}
    db.execute("UPDATE clients SET target_service='other-service' WHERE id='example-cli'")
    assert effective(db) == set()
    db.close()
