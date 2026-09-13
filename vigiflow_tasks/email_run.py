"""The email-driven run: what the trigger carries, and what comes back.

The process is started by an email with the list of links attached. Everything
the reply needs to say later, the sender, the file's name, when the run began,
travels on every work item so the reporter can compose that reply without
going back to the trigger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ADDRESS = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


@dataclass
class RunContext:
    """What every work item of one run carries."""

    run_id: str
    reply_to: str
    input_file: str
    started_at: str
    subject: str = ""
    sender_name: str = ""
    total_links: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "reply_to": self.reply_to,
            "input_file": self.input_file,
            "started_at": self.started_at,
            "subject": self.subject,
            "sender_name": self.sender_name,
            "total_links": self.total_links,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "RunContext":
        return cls(
            run_id=str(payload.get("run_id") or ""),
            reply_to=str(payload.get("reply_to") or ""),
            input_file=str(payload.get("input_file") or ""),
            started_at=str(payload.get("started_at") or ""),
            subject=str(payload.get("subject") or ""),
            sender_name=str(payload.get("sender_name") or ""),
            total_links=int(payload.get("total_links") or 0),
        )

    @property
    def started(self) -> datetime:
        try:
            return datetime.fromisoformat(self.started_at)
        except ValueError:
            return datetime.now(timezone.utc)


@dataclass
class TriggerEmail:
    """The email that started the run."""

    sender: str = ""
    sender_name: str = ""
    subject: str = ""
    attachments: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def reply_to(self) -> str:
        return self.sender


def read_trigger(item, output_dir: Path) -> TriggerEmail:
    """Pull the sender and the attachment out of the triggering work item.

    Control Room puts the parsed email on the work item and its attachments in
    the item's files. A run started by hand has neither, which is not an
    error: the caller falls back to a configured file.
    """
    trigger = TriggerEmail()

    email = None
    try:
        email = item.email(html=False)
    except Exception:
        # No email on this item, which is the normal case for a manual run.
        payload = item.payload if isinstance(item.payload, dict) else {}
        raw = payload.get("email") or {}
        if raw:
            trigger.sender = str(raw.get("from") or raw.get("From") or "")
            trigger.subject = str(raw.get("subject") or raw.get("Subject") or "")

    if email is not None:
        sender = getattr(email, "from_", None)
        trigger.sender = getattr(sender, "address", None) or str(sender or "")
        trigger.sender_name = getattr(sender, "name", "") or ""
        trigger.subject = getattr(email, "subject", "") or ""

    if not trigger.sender:
        payload = item.payload if isinstance(item.payload, dict) else {}
        found = ADDRESS.search(str(payload.get("reply_to") or payload.get("from") or ""))
        if found:
            trigger.sender = found.group(0)

    output_dir.mkdir(parents=True, exist_ok=True)
    for name in item.files:
        if not name.lower().endswith((".xlsx", ".xlsm", ".csv")):
            trigger.notes.append(f"ignored attachment {name}, not a spreadsheet")
            continue
        trigger.attachments.append(Path(item.get_file(name, output_dir / name)))

    return trigger
