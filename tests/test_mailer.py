"""The summary that goes with the emailed report."""

from datetime import datetime

import pytest

from vigiflow_tasks.mailer import MailError, format_summary, send_report

STARTED = datetime(2026, 9, 12, 9, 0, 0)
FINISHED = datetime(2026, 9, 12, 9, 4, 35)


def _summary(**over):
    args = dict(
        input_file="Links.xlsx", started=STARTED, finished=FINISHED,
        requested=12, written=12, failed=0, rows=12,
        filename="REPORTES DEL VIGIFLOW DEL DIA 12-09-2026.xlsx",
    )
    args.update(over)
    return format_summary(**args)


def test_the_summary_names_the_input_file_and_the_attachment():
    text = _summary()
    assert "Links.xlsx" in text
    assert "REPORTES DEL VIGIFLOW DEL DIA 12-09-2026.xlsx" in text


def test_the_duration_is_reported_in_minutes_and_seconds():
    assert "4 min 35 s" in _summary()


def test_a_short_run_reports_seconds_alone():
    finished = datetime(2026, 9, 12, 9, 0, 12)
    assert "12 s" in _summary(finished=finished)
    assert "min" not in _summary(finished=finished)


def test_a_complete_run_does_not_mention_failures():
    """Otherwise every run looks like it had a problem."""
    assert "Could not read" not in _summary()


def test_a_partial_run_says_how_many_were_missed():
    text = _summary(requested=12, written=9, failed=3)
    assert "Could not read  3" in text
    assert "Links received  12" in text


def test_notes_reach_the_reader():
    text = _summary(notes=["3 rows have no EV."])
    assert "3 rows have no EV." in text


def test_an_address_that_is_not_one_is_refused_before_connecting():
    """No point opening an SMTP session for a recipient that cannot exist."""
    with pytest.raises(MailError, match="No usable address"):
        send_report(to="not an address", subject="x", body="y")


def test_a_name_and_address_pair_is_accepted():
    from email.utils import parseaddr

    assert parseaddr("Jose <jose@example.com>")[1] == "jose@example.com"


@pytest.mark.parametrize("bad", ["", "   ", "nobody", "no@domain", "@example.com", "a b@c.d"])
def test_addresses_that_cannot_work_are_refused(bad):
    with pytest.raises(MailError, match="No usable address"):
        send_report(to=bad, subject="x", body="y")


def test_an_app_password_pasted_with_spaces_still_works(monkeypatch):
    """Google shows App Passwords as four blocks of four.

    Pasted in as shown, the spaces make the login fail with the same 535 as a
    wrong password, so they are stripped before use.
    """
    from vigiflow_tasks.mailer import SmtpConfig

    monkeypatch.setenv("VIGIFLOW_SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("VIGIFLOW_SMTP_USERNAME", " sender@example.org ")
    monkeypatch.setenv("VIGIFLOW_SMTP_PASSWORD", "abcd efgh ijkl mnop")
    config = SmtpConfig.from_vault()
    assert config.password == "abcdefghijklmnop"
    assert config.username == "sender@example.org"


@pytest.mark.parametrize(
    "value,expected",
    [("true", True), ("True", True), ("1", True), ("ssl", True),
     ("false", False), ("no", False), ("", False), (None, False)],
)
def test_smtp_secure_decides_implicit_tls(monkeypatch, value, expected):
    """secure means TLS from the first byte, not "encrypted or not".

    With it false the connection still upgrades through STARTTLS when the
    server offers it, which is what port 587 expects.
    """
    from vigiflow_tasks.mailer import SmtpConfig

    monkeypatch.setenv("VIGIFLOW_SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("VIGIFLOW_SMTP_USERNAME", "sender@example.org")
    monkeypatch.setenv("VIGIFLOW_SMTP_PASSWORD", "secret")
    if value is None:
        monkeypatch.delenv("VIGIFLOW_SMTP_SECURE", raising=False)
    else:
        monkeypatch.setenv("VIGIFLOW_SMTP_SECURE", value)
    assert SmtpConfig.from_vault().secure is expected
