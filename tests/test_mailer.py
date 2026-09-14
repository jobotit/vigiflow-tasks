"""The summary that goes with the emailed report.

The reply is for analysts in Lima, so it is in Spanish and its times are Lima
time, whatever clock the worker that sent it keeps.
"""

import sys
import types
from datetime import date, datetime, timezone

import pytest

from vigiflow_tasks import config
from vigiflow_tasks.mailer import BROKEN_LINK, MailError, format_summary, send_report

# The process records its times in UTC.
STARTED = datetime(2026, 9, 12, 9, 0, 0, tzinfo=timezone.utc)
FINISHED = datetime(2026, 9, 12, 9, 4, 35, tzinfo=timezone.utc)


def _summary(**over):
    args = dict(
        input_file="Links.xlsx", started=STARTED, finished=FINISHED,
        requested=12, written=12, failed=0, rows=12,
        filename="REPORTES DEL VIGIFLOW DEL DIA 12-09-2026.xlsx",
    )
    args.update(over)
    return format_summary(**args)


def _value(text, label):
    """The value printed beside a label, or None if the label is absent."""
    for line in text.splitlines():
        if line.strip().startswith(label):
            return line.strip()[len(label):].strip()
    return None


@pytest.fixture(autouse=True)
def _lima(monkeypatch):
    monkeypatch.delenv("VIGIFLOW_TIMEZONE", raising=False)
    monkeypatch.delenv("VIGIFLOW_VALIDATION_DATE", raising=False)


# -- language ----------------------------------------------------------------


def test_the_summary_names_the_input_file_and_the_attachment():
    text = _summary()
    assert text.startswith("Adjuntamos el reporte de VigiFlow")
    assert _value(text, "Archivo recibido") == "Links.xlsx"
    assert _value(text, "Archivo adjunto") == "REPORTES DEL VIGIFLOW DEL DIA 12-09-2026.xlsx"


def test_a_run_with_nothing_to_attach_says_so():
    text = _summary(written=0, rows=0, failed=12, filename=None)
    assert text.startswith("No se adjunta ningún reporte")
    assert _value(text, "Archivo adjunto") == "ninguno"


def test_the_duration_is_reported_in_minutes_and_seconds():
    assert _value(_summary(), "Duración") == "4 min 35 s"


def test_a_short_run_reports_seconds_alone():
    finished = datetime(2026, 9, 12, 9, 0, 12, tzinfo=timezone.utc)
    assert _value(_summary(finished=finished), "Duración") == "12 s"


def test_a_complete_run_does_not_mention_failures():
    """Otherwise every run looks like it had a problem."""
    assert _value(_summary(), "No se pudieron leer") is None


def test_a_partial_run_says_how_many_were_missed():
    text = _summary(requested=12, written=9, failed=3)
    assert _value(text, "No se pudieron leer") == "3"
    assert _value(text, "Enlaces recibidos") == "12"


def test_notes_reach_the_reader():
    text = _summary(notes=["3 filas no tienen EV."])
    assert "Observaciones:" in text
    assert "  - 3 filas no tienen EV." in text


def test_broken_links_are_reported_in_spanish_with_their_screenshot():
    text = _summary(broken=[{
        "row": 3,
        "value": "https://vigiflow.who-umc.org/dataentry/x",
        "detail": "La página que abre no es un reporte.",
        "screenshot": "enlace-fila-3.png",
    }])
    assert "1 enlace no se pudo usar:" in text
    assert f"Fila 3   {BROKEN_LINK}" in text
    assert "Captura adjunta: enlace-fila-3.png" in text


def test_several_broken_links_read_as_plural():
    text = _summary(broken=[{"row": 3}, {"row": 4}])
    assert "2 enlaces no se pudieron usar:" in text


def test_the_footer_is_in_spanish():
    assert _summary().rstrip().endswith("Las respuestas a este correo no se leen.")


# -- time zone -----------------------------------------------------------------


def test_times_are_shown_in_lima_and_the_zone_is_named():
    text = _summary()
    assert _value(text, "Inicio") == "12-09-2026 04:00:00"
    assert _value(text, "Fin") == "12-09-2026 04:04:35"
    assert _value(text, "Zona horaria") == "Lima (UTC-05:00)"


def test_a_utc_evening_is_still_the_previous_day_in_lima():
    """01:30 UTC on the 15th is 20:30 on the 14th for the analyst."""
    late = datetime(2026, 9, 15, 1, 30, 0, tzinfo=timezone.utc)
    text = _summary(started=late, finished=late)
    assert _value(text, "Inicio") == "14-09-2026 20:30:00"


def test_a_time_with_no_zone_is_taken_as_utc_not_the_workers_clock():
    naive = datetime(2026, 9, 12, 9, 0, 0)
    assert _value(_summary(started=naive, finished=naive), "Inicio") == "12-09-2026 04:00:00"


def test_lima_still_works_without_the_time_zone_database(monkeypatch):
    """Python on Windows ships without it. Peru has no daylight saving."""
    broken = types.ModuleType("zoneinfo")

    def no_database(name):
        raise LookupError(name)

    broken.ZoneInfo = no_database
    monkeypatch.setitem(sys.modules, "zoneinfo", broken)

    assert config.local_timezone() is config.LIMA_FIXED
    assert _value(_summary(), "Inicio") == "12-09-2026 04:00:00"


def test_an_unknown_time_zone_is_an_error_not_a_quiet_fallback(monkeypatch):
    monkeypatch.setenv("VIGIFLOW_TIMEZONE", "Mars/Olympus_Mons")
    with pytest.raises(config.ConfigError, match="Mars/Olympus_Mons"):
        config.local_timezone()


def test_the_validation_date_is_today_in_lima(monkeypatch):
    """A UTC worker after 19:00 in Lima would otherwise stamp tomorrow."""

    class LateEvening(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 15, 1, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(config, "datetime", LateEvening)
    assert config.resolve_validation_date({}) == date(2026, 9, 14)


# -- sending -----------------------------------------------------------------


def test_the_spanish_sender_name_survives_mail_encoding(monkeypatch):
    from vigiflow_tasks import mailer
    from vigiflow_tasks.mailer import SmtpConfig

    monkeypatch.setenv("VIGIFLOW_SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("VIGIFLOW_SMTP_USERNAME", "sender@example.org")
    monkeypatch.setenv("VIGIFLOW_SMTP_PASSWORD", "secret")
    sent = []
    monkeypatch.setattr(mailer, "_deliver", lambda _config, message: sent.append(message))

    send_report(
        "analista@example.org", "Reporte de VigiFlow: Links.xlsx", _summary(),
        config=SmtpConfig.from_vault(),
    )

    message = sent[0]
    assert message.as_bytes()  # encodes without error
    assert "Automatización VigiFlow" in str(message["From"])
    assert "Adjuntamos el reporte" in message.get_content()


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
    smtp = SmtpConfig.from_vault()
    assert smtp.password == "abcdefghijklmnop"
    assert smtp.username == "sender@example.org"


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
