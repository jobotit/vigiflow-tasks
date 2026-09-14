"""Sending the finished report back to whoever asked for it.

Plain smtplib rather than a library: it is in the standard library, works the
same on Linux, and needs nothing beyond an SMTP account in the vault.

The credentials live in a vault item alongside the VigiFlow ones. Nothing here
prints a password, and the recipient is echoed so a run's log says where the
report went.
"""

from __future__ import annotations

import logging
import mimetypes
import re
import smtplib
from dataclasses import dataclass
from datetime import timezone
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from pathlib import Path
from typing import Any, Iterable

from vigiflow_tasks.config import local_timezone

LOGGER = logging.getLogger(__name__)

# Deliberately simple: enough to reject nonsense before connecting.
ADDRESS = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

DEFAULT_VAULT_SECRET = "Vigiflow_C001_Credentials"
DEFAULT_PORT = 587

# What a link that is not a report is called in the reply. Kept here so the
# wording is the same whether the producer rejected the cell or the consumer
# opened it and found something that was not a report.
BROKEN_LINK = "El enlace proporcionado está roto o no corresponde a un reporte."

# The reply is for the client's analysts in Lima, so it is written in Spanish
# and every time in it is Lima time. Labels are padded to this width so the
# values line up in a plain-text mail client.
LABEL_WIDTH = 22

# Keys accepted in the vault item, in the order they are tried.
HOST_KEYS = ("SMTP_HOST", "smtp_host", "host", "server")
PORT_KEYS = ("SMTP_PORT", "smtp_port", "port")
USER_KEYS = ("SMTP_USERNAME", "smtp_username", "SMTP_USER", "GMAIL_USER", "username", "user")
PASSWORD_KEYS = (
    "SMTP_PASSWORD", "smtp_password", "GMAIL_PASSWORD", "gmail_password", "password", "clave"
)
FROM_KEYS = ("SMTP_FROM", "smtp_from", "GMAIL_USER", "from", "sender")
SECURE_KEYS = ("SMTP_SECURE", "smtp_secure", "secure", "ssl", "tls")

# Google is the common case here and needs no host in the vault: an item that
# carries a GMAIL_PASSWORD is taken to mean Gmail, and the account name falls
# back to the VigiFlow login, which is itself an email address.
GMAIL_MARKERS = ("GMAIL_PASSWORD", "gmail_password")
GMAIL_HOST = "smtp.gmail.com"
GMAIL_PORT = 587
VIGIFLOW_USER_KEYS = ("VIGIFLOW_USERNAME", "username", "user")


class MailError(RuntimeError):
    """The report could not be sent."""


@dataclass
class SmtpConfig:
    """How to reach the SMTP server.

    ``secure`` follows the convention the mail libraries use, which is not the
    same as "encrypted or not":

    ``True``   implicit TLS, wrapped from the first byte. Port 465.
    ``False``  connect in the clear, then upgrade with STARTTLS if the server
               offers it. Ports 587 and 25. This is the usual setting, and it
               still ends up encrypted whenever the server supports it.
    """

    host: str
    port: int
    username: str
    password: str
    sender: str
    secure: bool = False
    password_key: str = ""  # which vault key supplied it, for diagnosis

    def describe_password(self) -> str:
        """The shape of the password, never the password.

        A Google App Password is exactly 16 lowercase letters. Anything else
        against smtp.gmail.com is almost certainly an account password, which
        Google will refuse, and this says so without printing a secret.
        """
        length = len(self.password)
        kinds = []
        if any(c.isupper() for c in self.password):
            kinds.append("upper")
        if any(c.islower() for c in self.password):
            kinds.append("lower")
        if any(c.isdigit() for c in self.password):
            kinds.append("digits")
        if any(not c.isalnum() for c in self.password):
            kinds.append("symbols")
        shape = f"{length} characters, {'+'.join(kinds) or 'empty'}"
        if length == 16 and kinds == ["lower"]:
            return f"{shape}, which is the shape of a Google App Password"
        return shape

    @classmethod
    def from_vault(cls, secret_name: str | None = None) -> "SmtpConfig":
        """Read the SMTP account, with environment overrides for local runs."""
        import os

        def env(name: str) -> str | None:
            value = os.environ.get(name)
            return value.strip() if value and value.strip() else None

        secure = env("VIGIFLOW_SMTP_SECURE")
        host = env("VIGIFLOW_SMTP_HOST")
        port = env("VIGIFLOW_SMTP_PORT")
        username = env("VIGIFLOW_SMTP_USERNAME")
        password = env("VIGIFLOW_SMTP_PASSWORD")
        password_key = "VIGIFLOW_SMTP_PASSWORD" if password else ""
        sender = env("VIGIFLOW_SMTP_FROM")

        if not (host and username and password):
            from robocorp import vault

            name = secret_name or env("VIGIFLOW_SMTP_SECRET") or DEFAULT_VAULT_SECRET
            secret = vault.get_secret(name)
            gmail = any(_optional(secret, (key,)) for key in GMAIL_MARKERS)

            host = host or _optional(secret, HOST_KEYS) or (GMAIL_HOST if gmail else None)
            port = port or _optional(secret, PORT_KEYS) or (GMAIL_PORT if gmail else None)
            username = (
                username
                or _optional(secret, USER_KEYS)
                or (_optional(secret, VIGIFLOW_USER_KEYS) if gmail else None)
            )
            password_key = next(
                (k for k in PASSWORD_KEYS if _optional(secret, (k,))), ""
            )
            password = password or _pick(secret, PASSWORD_KEYS, name, "SMTP password")
            sender = sender or _optional(secret, FROM_KEYS) or username
            secure = secure if secure is not None else _optional(secret, SECURE_KEYS)

            if not host:
                raise MailError(
                    f"Vault item {name!r} has no SMTP host, and nothing marks it as "
                    "Gmail. Add SMTP_HOST, or GMAIL_PASSWORD to use Gmail."
                )
            if not username:
                raise MailError(
                    f"Vault item {name!r} has no SMTP username. Add SMTP_USERNAME, "
                    "or GMAIL_USER if the sending account differs from the VigiFlow login."
                )

        return cls(
            host=host,
            port=int(port or DEFAULT_PORT),
            username=(username or "").strip(),
            # Google shows an App Password as four blocks of four, and the
            # spaces are display only. Pasted in as shown they make the login
            # fail with the same 535 as a wrong password, which is a long way
            # to chase a space.
            password=re.sub(r"\s+", "", password or ""),
            password_key=password_key,
            sender=sender or username,
            secure=str(secure or "").strip().lower() in ("1", "true", "yes", "ssl"),
        )


def _pick(secret: Any, candidates: Iterable[str], name: str, label: str) -> str:
    for key in candidates:
        try:
            value = secret[key]
        except (KeyError, TypeError):
            continue
        if value:
            return str(value)
    try:
        present = sorted(secret.keys())
    except Exception:  # pragma: no cover
        present = []
    raise MailError(
        f"Vault item {name!r} has no {label}. Keys present: {present or 'unknown'}"
    )


def _optional(secret: Any, candidates: Iterable[str]) -> str | None:
    for key in candidates:
        try:
            value = secret[key]
        except (KeyError, TypeError):
            continue
        if value:
            return str(value)
    return None


def send_report(
    to: str,
    subject: str,
    body: str,
    attachments: Path | Iterable[Path] | None = None,
    config: SmtpConfig | None = None,
    cc: str | None = None,
    reply_to: str | None = None,
) -> str:
    """Send the finished report. Returns the address it went to.

    ``attachments`` takes one path or several: the workbook, plus a screenshot
    for each link that turned out not to be a report. A path that no longer
    exists is skipped rather than failing the send, because a missing
    screenshot is not worth losing the report over.

    The From address can differ from the account that signs in, which is how
    a no-reply sender works. Providers only allow it for an address the
    account owns or has configured as an alias, and Google silently rewrites
    the header otherwise, so what the recipient sees is worth checking once.
    """
    recipient = parseaddr(to or "")[1]
    # parseaddr is lenient and will hand back nonsense rather than nothing, so
    # the shape is checked here. Failing now costs a line; failing after the
    # SMTP session opens wastes the connection and muddies the error.
    if not recipient or not ADDRESS.fullmatch(recipient):
        raise MailError(f"No usable address to reply to in {to!r}")

    config = config or SmtpConfig.from_vault()
    message = EmailMessage()
    message["From"] = formataddr(("Automatización VigiFlow", config.sender))
    message["To"] = recipient
    if cc:
        message["Cc"] = cc
    if reply_to:
        # A no-reply From still needs somewhere for a person to write back to.
        message["Reply-To"] = reply_to
    message["Subject"] = subject
    message.set_content(body)

    for attachment in _as_paths(attachments):
        if not attachment.exists():
            LOGGER.warning("Not attaching %s: it is no longer there", attachment.name)
            continue
        guessed, _ = mimetypes.guess_type(attachment.name)
        maintype, _, subtype = (guessed or "application/octet-stream").partition("/")
        message.add_attachment(
            attachment.read_bytes(),
            maintype=maintype,
            subtype=subtype or "octet-stream",
            filename=attachment.name,
        )

    try:
        _deliver(config, message)
    except smtplib.SMTPAuthenticationError as err:
        # Name what was tried, never the password, so the vault can be fixed
        # without another round trip.
        hint = ""
        if "gmail" in config.host.lower() or "google" in config.host.lower():
            hint = (
                " Google rejects an ordinary account password over SMTP. The "
                "vault needs a 16 character App Password for this account, "
                "generated at myaccount.google.com/apppasswords, and the account "
                "must have 2-step verification on for that page to exist. For a "
                "Workspace domain an administrator may also have to allow it."
            )
        raise MailError(
            f"{config.host} rejected the sign-in for {config.username}.{hint} "
            f"({err.smtp_code})"
        ) from err
    except Exception as err:
        raise MailError(
            f"Could not send to {recipient} through {config.host}:{config.port}: {err}"
        ) from err

    LOGGER.info("Report sent to %s", recipient)
    return recipient


def _as_paths(attachments: Path | Iterable[Path] | None) -> list[Path]:
    """One path, several, or none, as a list."""
    if attachments is None:
        return []
    if isinstance(attachments, (str, Path)):
        return [Path(attachments)]
    return [Path(a) for a in attachments if a]


def _deliver(config: SmtpConfig, message: EmailMessage) -> None:
    """Open the right kind of connection and send.

    With ``secure`` the socket is TLS from the first byte. Without it the
    connection starts in the clear and is upgraded with STARTTLS when the
    server advertises it, which is what almost every server on port 587 wants.
    A server that offers no STARTTLS is used as it is rather than failed on,
    because refusing would leave the report undeliverable for a setting the
    administrator chose.
    """
    if config.secure:
        with smtplib.SMTP_SSL(config.host, config.port, timeout=60) as smtp:
            smtp.login(config.username, config.password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(config.host, config.port, timeout=60) as smtp:
        smtp.ehlo()
        if smtp.has_extn("starttls"):
            smtp.starttls()
            smtp.ehlo()
        else:
            LOGGER.warning(
                "%s offers no STARTTLS, so this message goes unencrypted", config.host
            )
        smtp.login(config.username, config.password)
        smtp.send_message(message)


def check_connection(config: SmtpConfig) -> dict:
    """Reach the server and try to sign in, reporting each stage separately.

    Connecting, upgrading to TLS and authenticating fail for different reasons
    and want different fixes. A single "could not send" hides which one, so
    each is reported on its own.
    """
    result = {"connected": False, "starttls": None, "authenticated": False, "error": ""}
    try:
        if config.secure:
            smtp = smtplib.SMTP_SSL(config.host, config.port, timeout=30)
            result["starttls"] = "implicit TLS"
        else:
            smtp = smtplib.SMTP(config.host, config.port, timeout=30)
        result["connected"] = True
    except Exception as err:
        result["error"] = f"could not reach {config.host}:{config.port}: {err}"
        return result

    try:
        with smtp:
            if not config.secure:
                smtp.ehlo()
                if smtp.has_extn("starttls"):
                    smtp.starttls()
                    smtp.ehlo()
                    result["starttls"] = "upgraded with STARTTLS"
                else:
                    result["starttls"] = "not offered, would send in the clear"
            try:
                smtp.login(config.username, config.password)
                result["authenticated"] = True
            except smtplib.SMTPAuthenticationError as err:
                result["error"] = f"{err.smtp_code} {err.smtp_error!r}"
    except Exception as err:
        result["error"] = result["error"] or str(err)
    return result


def _local(moment):
    """A moment in the client's time zone.

    The process records its times in UTC. A value with no zone attached is
    taken to be UTC too, rather than the clock of whichever worker ran it.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(local_timezone())


def _zone_label(moment) -> str:
    """"Lima (UTC-05:00)", so the reader never has to wonder which clock."""
    zone = moment.tzinfo
    name = getattr(zone, "key", None) or str(zone)
    place = name.split("/")[-1].replace("_", " ")
    offset = moment.strftime("%z")
    return f"{place} (UTC{offset[:3]}:{offset[3:]})"


def format_summary(
    input_file: str,
    started,
    finished,
    requested: int,
    written: int,
    failed: int,
    rows: int,
    filename: str | None,
    notes: list[str] | None = None,
    broken: list[dict] | None = None,
) -> str:
    """The short note that goes with the report, in Spanish and in Lima time.

    Says what was asked for, what came back, and how long it took, so the
    recipient can tell a complete run from a partial one without opening the
    workbook. Dates are written day first, as the business writes them in the
    workbook's own filename.

    ``broken`` lists the rows that were not reports. Each is named by its row
    in the spreadsheet the analyst sent, which is the thing they can act on,
    and by the screenshot attached to this message where there is one.
    """
    started, finished = _local(started), _local(finished)
    elapsed = finished - started
    minutes, seconds = divmod(int(elapsed.total_seconds()), 60)
    duration = f"{minutes} min {seconds} s" if minutes else f"{seconds} s"

    def row(label, value):
        return f"  {label:<{LABEL_WIDTH}}{value}"

    opening = (
        "Adjuntamos el reporte de VigiFlow que solicitó."
        if rows
        else "No se adjunta ningún reporte: no se pudo leer ningún enlace de la lista."
    )
    lines = [
        opening,
        "",
        row("Archivo recibido", input_file),
        row("Enlaces recibidos", requested),
        row("Reportes leídos", written),
    ]
    if failed:
        lines.append(row("No se pudieron leer", failed))
    lines += [
        row("Filas escritas", rows),
        row("Archivo adjunto", filename or "ninguno"),
        "",
        row("Inicio", f"{started:%d-%m-%Y %H:%M:%S}"),
        row("Fin", f"{finished:%d-%m-%Y %H:%M:%S}"),
        row("Duración", duration),
        row("Zona horaria", _zone_label(started)),
    ]

    if broken:
        count = len(broken)
        heading = "1 enlace no se pudo usar:" if count == 1 else f"{count} enlaces no se pudieron usar:"
        lines += ["", heading]
        for entry in broken:
            lines.append("")
            lines.append(f"  Fila {entry.get('row', '?')}   {BROKEN_LINK}")
            value = str(entry.get("value") or "").strip()
            if value:
                lines.append(f"          {value}")
            detail = str(entry.get("detail") or "").strip()
            if detail:
                lines.append(f"          {detail}")
            shot = str(entry.get("screenshot") or "").strip()
            if shot:
                lines.append(f"          Captura adjunta: {shot}")

    if notes:
        lines += ["", "Observaciones:"] + [f"  - {n}" for n in notes]
    lines += ["", "Mensaje enviado automáticamente. Las respuestas a este correo no se leen."]
    return "\n".join(lines)
