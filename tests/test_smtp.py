"""No network calls: real worker state handling with an injected fake SMTP transport."""
from pathlib import Path
import smtplib
import pytest
from smtp_worker import deliver, process, worker_lock
from sql_harness import Clock, connect, initialize, create, enqueue

JOB = {'id':'operation', 'recipient':'test@example.invalid', 'subject':'HumanGrant permission request', 'body':'Fixed body'}


class SMTP:
    def __init__(self, phase=None, result=None):
        self.phase = phase
        self.result = result
        self.messages = []
    def response(self, phase):
        if self.phase == phase:
            if isinstance(self.result, Exception):
                raise self.result
            return self.result, b'not logged'
        return 250, b'ok'
    def mail(self, sender):
        return self.response('mail')
    def rcpt(self, recipient):
        return self.response('rcpt')
    def data(self, message):
        self.messages.append(message)
        return self.response('data')


@pytest.mark.parametrize('phase,result,expected', [
    (None,None,'transport_accepted'), ('mail',550,'failed'), ('rcpt',550,'failed'),
    ('mail',TimeoutError(),'failed'), ('rcpt',smtplib.SMTPServerDisconnected(),'failed'),
    ('data',550,'failed'), ('data',smtplib.SMTPDataError(550,b'no'),'failed'),
    ('data',TimeoutError(),'delivery_unknown'), ('data',smtplib.SMTPServerDisconnected(),'delivery_unknown')])
def test_delivery_boundary(phase,result,expected):
    smtp = SMTP(phase,result)
    assert deliver(JOB,smtp,'noreply@example.invalid') == expected
    if phase in {'mail','rcpt'}:
        assert not smtp.messages


def test_sender_header_injection_rejected():
    with pytest.raises(ValueError):
        deliver(JOB,SMTP(),'sender@example.invalid\r\nBcc: other@example.invalid')


def test_worker_requires_initialized_database(tmp_path):
    with pytest.raises(ValueError):
        process(tmp_path/'missing',lambda job:'transport_accepted')


@pytest.mark.parametrize('state', ['transport_accepted','failed','delivery_unknown'])
def test_worker_records_outcome_and_does_not_retry(tmp_path, state):
    path = tmp_path/'outbox.db'
    clock = Clock()
    db = connect(path,clock)
    initialize(db)
    create(db,clock)
    enqueue(db)
    calls = []
    def transport(job):
        calls.append(job['id'])
        return state
    with worker_lock(path):
        assert process(path,transport,clock=lambda:clock.now) == [('op1',state)]
        assert process(path,transport,clock=lambda:clock.now) == []
    assert calls == ['op1']
    assert db.execute("SELECT state FROM mail_operations").fetchone()[0] == state
    db.close()


def test_worker_crash_recovery_is_unknown_not_resent(tmp_path):
    path = tmp_path/'outbox.db'
    clock = Clock()
    db = connect(path,clock)
    initialize(db)
    create(db,clock)
    enqueue(db)
    db.execute("UPDATE mail_operations SET state='sending'")
    with worker_lock(path):
        assert process(path,lambda job:pytest.fail('Must not retransmit'),clock=lambda:clock.now) == []
    assert db.execute("SELECT state FROM mail_operations").fetchone()[0] == 'delivery_unknown'
    db.close()


def test_worker_does_not_send_expired_job(tmp_path):
    path = tmp_path/'outbox.db'
    clock = Clock()
    db = connect(path,clock)
    initialize(db)
    create(db,clock)
    enqueue(db)
    clock.advance(601)
    with worker_lock(path):
        assert process(path,lambda job:pytest.fail('Expired job sent'),clock=lambda:clock.now) == []
    assert db.execute("SELECT state FROM mail_operations").fetchone()[0] == 'expired'
    db.close()


def test_second_worker_cannot_take_same_lock(tmp_path):
    path = tmp_path/'outbox.db'
    with worker_lock(path):
        with pytest.raises(BlockingIOError):
            with worker_lock(path):
                pytest.fail('Two workers acquired the lock')


def test_missing_sender_is_a_definite_failure_before_network(monkeypatch):
    import smtp_worker
    monkeypatch.delenv('HG_SMTP_FROM', raising=False)
    monkeypatch.setattr(smtp_worker, 'connect_smtp', lambda:pytest.fail('No sender; no connection allowed'))
    assert smtp_worker.network_transport(JOB) == 'failed'


def test_close_failure_does_not_erase_positive_data_reply(monkeypatch):
    import smtp_worker
    smtp = SMTP()
    def close():
        raise OSError('socket close failure')
    smtp.close = close
    monkeypatch.setenv('HG_SMTP_FROM', 'noreply@example.invalid')
    monkeypatch.setattr(smtp_worker, 'connect_smtp', lambda:smtp)
    assert smtp_worker.network_transport(JOB) == 'transport_accepted'
