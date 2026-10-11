#!/usr/bin/env python3
"""Optional, one-pass outbox worker. Default HumanGrant needs no SMTP process.

Only this command permits network mail, and only with --allow-network. Unit tests
inject a transport. This worker never retries an ambiguous SMTP DATA operation.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from email.message import EmailMessage
import json
import os
from pathlib import Path
import smtplib
import sqlite3
import ssl
import sys
import time
from typing import Any, Callable, Iterator

ROOT = Path(__file__).resolve().parents[1]


def deliver(job: dict[str, str], smtp: Any, sender: str) -> str:
    """Use fixed database-generated content; distinguish pre-DATA failures.

A positive final DATA reply means that the SMTP server accepted the message.
It does not mean that the destination received it. Exceptions during DATA may
mean either success or failure and must not result in automatic retransmission.
"""
    if any(c in sender for c in '\r\n') or '@' not in sender:
        raise ValueError('Invalid configured sender')
    message = EmailMessage()
    message['From'] = sender
    message['To'] = job['recipient']
    message['Subject'] = job['subject']
    message['Message-ID'] = f"<{job['id']}@humangrant.invalid>"
    message.set_content(job['body'])
    try:
        code, _ = smtp.mail(sender)
        if code != 250:
            return 'failed'
        code, _ = smtp.rcpt(job['recipient'])
        if code not in (250, 251):
            return 'failed'
    except (smtplib.SMTPException, OSError):
        return 'failed'
    try:
        code, _ = smtp.data(message.as_bytes())
        return 'transport_accepted' if code == 250 else 'failed'
    except smtplib.SMTPDataError:
        # A received negative SMTP reply is a definite rejection.
        return 'failed'
    except (smtplib.SMTPException, OSError):
        return 'delivery_unknown'


def connect_smtp() -> Any:
    host = os.environ.get('HG_SMTP_HOST', '')
    if not host or any(c in host for c in '\r\n'):
        raise ValueError('Set HG_SMTP_HOST')
    port = int(os.environ.get('HG_SMTP_PORT', '465'))
    mode = os.environ.get('HG_SMTP_TLS', 'implicit')
    timeout = float(os.environ.get('HG_SMTP_TIMEOUT', '15'))
    if not 1 <= timeout <= 120 or not 1 <= port <= 65535:
        raise ValueError('Invalid SMTP port or timeout')
    context = ssl.create_default_context()
    if mode == 'implicit':
        smtp = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
    elif mode == 'starttls':
        smtp = smtplib.SMTP(host, port, timeout=timeout)
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
    else:
        raise ValueError('Only implicit TLS or STARTTLS is supported')
    user = os.environ.get('HG_SMTP_USER')
    if user:
        password = os.environ.get('HG_SMTP_PASSWORD')
        if not password:
            smtp.close()
            raise ValueError('Set HG_SMTP_PASSWORD for authentication')
        smtp.login(user, password)
    return smtp


@contextmanager
def worker_lock(database: Path) -> Iterator[None]:
    """A local OS lock, not a network service. Reference worker targets Unix."""
    import fcntl
    descriptor = os.open(str(database) + '.smtp.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def process(database: Path, transport: Callable[[dict[str, str]], str], *,
            clock: Callable[[], float] = time.time, limit: int = 10) -> list[tuple[str, str]]:
    """Process a bounded batch. Caller must hold worker_lock during this call."""
    if not database.is_file() or not 1 <= limit <= 100:
        raise ValueError('An initialized database and a limit from 1 to 100 are required')
    db = sqlite3.connect(database, timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    instant = [int(clock())]
    db.create_function('hg_now', 0, lambda: instant[0])
    results: list[tuple[str, str]] = []
    try:
        db.execute('PRAGMA foreign_keys=ON')
        if db.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise ValueError('Unsupported database schema')
        # Only the lock owner may classify interrupted attempts from a previous worker.
        db.execute("UPDATE mail_operations SET state='delivery_unknown',transport_updated_at=hg_now() WHERE state='sending'")
        for _ in range(limit):
            db.execute('BEGIN IMMEDIATE')
            instant[0] = int(clock())  # Take time AFTER obtaining the write lock.
            for statement in (ROOT / 'src/sql/expire.sql').read_text().split(';'):
                if statement.strip():
                    db.execute(statement)
            row = db.execute("SELECT id,recipient,subject,body FROM mail_operations WHERE state='queued' ORDER BY requested_at,id LIMIT 1").fetchone()
            if row is None:
                db.commit()
                break
            job = dict(row)
            db.execute("UPDATE mail_operations SET state='sending',transport_updated_at=hg_now() WHERE id=?", (job['id'],))
            db.commit()
            try:
                state = transport(job)
                if state not in {'failed', 'delivery_unknown', 'transport_accepted'}:
                    state = 'delivery_unknown'
            except Exception:
                # Unknown transport implementations may have already submitted DATA.
                state = 'delivery_unknown'
            instant[0] = int(clock())
            db.execute("UPDATE mail_operations SET state=?,transport_updated_at=hg_now() WHERE id=? AND state='sending'", (state, job['id']))
            results.append((job['id'], state))
        return results
    finally:
        db.close()


def network_transport(job: dict[str, str]) -> str:
    sender = os.environ.get('HG_SMTP_FROM', '')
    if not sender or any(c in sender for c in '\r\n') or '@' not in sender:
        return 'failed'
    try:
        smtp = connect_smtp()
    except (smtplib.SMTPException, OSError, ValueError):
        return 'failed'  # DATA has not been submitted.
    try:
        return deliver(job, smtp, sender)
    finally:
        try:
            smtp.close()  # Closing cannot change a successful final DATA result.
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--allow-network', action='store_true', help='Explicitly allow real SMTP sends')
    parser.add_argument('--limit', type=int, default=10)
    args = parser.parse_args()
    if not args.allow_network:
        parser.error('Real mail requires --allow-network; use local mode for development')
    config = json.loads(args.config.read_text())
    if config.get('mail', {}).get('mode') != 'smtp-worker':
        parser.error('The config must explicitly select mail.mode = smtp-worker')
    database = Path(config['database'])
    with worker_lock(database):
        for operation, state in process(database, network_transport, limit=args.limit):
            print(json.dumps({'operation_id': operation, 'transport_status': state}))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, sqlite3.Error):
        print('SMTP worker stopped; check local configuration and operator records.', file=sys.stderr)
        sys.exit(1)
