"""The email-driven process, in either of two shapes.

Three steps, for a Control Room process with one step per task:

    Producer   the triggering email carries a spreadsheet of report links.
               One work item per row, so each row is a transaction that can
               fail and be retried on its own. Rows that are not usable links
               are queued too, because a row dropped here is a report the
               analyst believes was processed and was not.

    Consumer   opens one report and reads its whole row from the page. A link
               that turns out not to be a report is photographed instead, so
               the reply can show what is actually there.

    Reporter   collects the rows, numbers them, writes one workbook, emails it
               back to whoever sent the list, and then deletes what the run
               created.

One step, for short lists:

    Single run   all three in one task. Each Control Room step starts its own
                 environment, and for a list of a few dozen links those
                 start-ups are the slow part of the run. This mode pays for
                 one. The trade-off is what Control Room can see: the rows are
                 not separate work items, so a bad link is not its own
                 exception, no row can be retried on its own, and a run that
                 fails midway keeps nothing it had read. Every row still
                 reaches the reply.

Both shapes run the same functions for starting a run, reading a row and
finishing a run, so the workbook and the reply are identical whichever shape
produced them.

The analyst chooses which reports to work on, so nothing here applies a filter
or walks a result page. A report is reached directly by the link supplied.

What the robot reads is sensitive and the workbook is not, so every task runs
inside `privacy.no_data_in_logs` and nothing printed here carries a value read
from a report. See `vigiflow_tasks/privacy.py`.
"""

import contextlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from robocorp import workitems
from robocorp.tasks import get_output_dir, task

from vigiflow_tasks import privacy
from vigiflow_tasks.causality import assign_ev_column
from vigiflow_tasks.config import (
    resolve_start_number,
    resolve_template,
    resolve_validation_date,
    template_path,
)
from vigiflow_tasks.email_run import RunContext, read_trigger
from vigiflow_tasks.excel.template_writer import ExcelTemplateWriter
from vigiflow_tasks.excel.template_writer import RunContext as SheetRun
from vigiflow_tasks.links import (
    NOT_A_REPORT_DETAIL,
    LinksError,
    read_links,
)
from vigiflow_tasks.mailer import MailError, format_summary, send_report
from vigiflow_tasks.models import ReportRecord
from vigiflow_tasks.report_scraper import scrape_report, screenshot
from vigiflow_tasks.vigiflow import open_client

# What the business calls the daily file, as seen in the sample it produces
# by hand: "REPORTES DEL VIGIFLOW DEL DIA 31-08-2026.xlsx".
DAILY_FILENAME = "REPORTES DEL VIGIFLOW DEL DIA {day}"
UNSAFE_IN_FILENAME = re.compile(r'[<>:"/\\|?*]')

# Fields of the run context that travel on every row of a run.
CONTEXT_KEYS = (
    "run_id",
    "reply_to",
    "input_file",
    "started_at",
    "subject",
    "sender_name",
    "total_links",
)

# Control Room exception codes for a row that is not a report, with the
# operator-facing message each one carries.
NOT_A_LINK = "NOT_A_LINK"
LINK_NOT_A_REPORT = "LINK_NOT_A_REPORT"
BROKEN_MESSAGES = {
    NOT_A_LINK: "Row {row} is not a VigiFlow address",
    LINK_NOT_A_REPORT: "Row {row} does not lead to a report",
}


def daily_filename(validation_date: date) -> str:
    """Name the output the way the business names it."""
    stem = DAILY_FILENAME.format(day=validation_date.strftime("%d-%m-%Y"))
    return UNSAFE_IN_FILENAME.sub("-", stem).strip() + ".xlsx"


# =============================================================================
# The three-step shape
# =============================================================================


@task
def email_producer() -> None:
    """Turn the emailed list into one work item per row."""
    output_dir = get_output_dir() or Path("output")
    started = datetime.now(timezone.utc)
    _sweep(output_dir)

    with privacy.no_data_in_logs():
        for item in workitems.inputs:
            begun = _start_run(item, output_dir, started)
            if begun is None:
                continue
            _, queued = begun
            for payload in queued:
                workitems.outputs.create(payload=payload)
            print(f"Queued {len(queued)} rows, one work item each")
            item.done()


@task
def email_consumer() -> None:
    """Read one report per work item, straight from its own page.

    One browser for the whole run rather than one per report: signing in again
    for each is the slowest thing the process could do.
    """
    output_dir = get_output_dir() or Path("output")
    tally = Tally()

    with privacy.no_data_in_logs():
        with open_client("browser") as client:
            client.login()

            for item in workitems.inputs:
                payload = item.payload if isinstance(item.payload, dict) else {}
                outcome = _read_row(client.page, payload, output_dir, tally)

                if outcome is None:
                    item.fail("APPLICATION", code="NO_URL", message="Work item carries no link")
                    continue

                if outcome.get("broken"):
                    # The screenshot travels as a file on the work item, so it
                    # survives the tasks running on different machines.
                    shot = outcome.pop("screenshot_path", None)
                    workitems.outputs.create(payload=outcome, files=[shot] if shot else None)
                    item.fail("BUSINESS", code=outcome["code"], message=_broken_message(outcome))
                    continue

                workitems.outputs.create(payload=outcome)
                item.done()

    tally.report()


@task
def email_reporter() -> None:
    """Write the workbook, email it back, and delete what the run created."""
    output_dir = get_output_dir() or Path("output")
    finished = datetime.now(timezone.utc)

    rows: list[dict] = []
    broken: list[dict] = []
    context: RunContext | None = None

    with privacy.no_data_in_logs():
        # The inputs are not released explicitly. Advancing the iterator
        # releases each in turn and the last goes when the loop ends, so
        # calling done() afterwards raises "work item already released".
        for item in workitems.inputs:
            payload = item.payload if isinstance(item.payload, dict) else {}
            if context is None and payload.get("reply_to"):
                context = RunContext.from_payload(payload)

            if payload.get("broken"):
                path = None
                for name in item.files:
                    path = str(item.get_file(name, output_dir / name))
                broken.append(_reply_entry(payload, path))
            elif payload.get("report_id"):
                rows.append(payload)

        if context is None:
            print("Nothing to report on: no work item carried a run to reply to.")
            return

        _finish_run(context, rows, broken, output_dir, finished)


# =============================================================================
# The single-task shape
# =============================================================================


@task
def email_single_run() -> None:
    """The whole process in one task: read the list, read every report, reply.

    One environment start-up and one sign-in, and no work items in between.
    The trigger email is the only work item, and it is completed once the
    reply has gone.
    """
    output_dir = get_output_dir() or Path("output")
    _sweep(output_dir)

    with privacy.no_data_in_logs():
        for item in workitems.inputs:
            begun = _start_run(item, output_dir, datetime.now(timezone.utc))
            if begun is None:
                continue
            context, queued = begun

            tally = Tally()
            outcomes = _read_rows(queued, output_dir, tally)
            tally.report()

            rows = [o for o in outcomes if not o.get("broken")]
            broken = [_reply_entry(o, o.get("screenshot_path")) for o in outcomes if o.get("broken")]
            _finish_run(context, rows, broken, output_dir, datetime.now(timezone.utc))
            item.done()


def _read_rows(queued: list[dict], output_dir: Path, tally: "Tally") -> list[dict]:
    """Read every row in one browser session, opened only if a row needs one.

    A list with no usable link at all still gets its reply, and does not pay
    for starting a browser and signing in to find out nothing could be read.
    """
    needs_browser = any(payload.get("url") for payload in queued)
    session = open_client("browser") if needs_browser else contextlib.nullcontext()
    outcomes: list[dict] = []
    with session as client:
        if client is not None:
            client.login()
        page = client.page if client is not None else None
        for payload in queued:
            outcome = _read_row(page, payload, output_dir, tally)
            if outcome is not None:
                outcomes.append(outcome)
    return outcomes


# =============================================================================
# Shared by both shapes
# =============================================================================


@dataclass
class Tally:
    """What the log says about reading a run, in counts only.

    Counted rather than named per row, so the log says how complete a run was
    without saying which report lacked what.
    """

    read: int = 0
    broken: int = 0
    partial: int = 0
    gaps: Counter = field(default_factory=Counter)
    blockers: Counter = field(default_factory=Counter)

    def report(self) -> None:
        print(f"Read {self.read} reports, {self.broken} links were not reports")
        if self.partial:
            print(f"  {self.partial} reports had a section that could not be opened")
        for title, count in sorted(self.blockers.items()):
            print(f"  {count} of them had a dialog covering the page: {title}")
        for name, count in sorted(self.gaps.items()):
            print(f"  {count} reports had no {name}")


def _sweep(output_dir: Path) -> None:
    """Clear what an earlier run left behind.

    Anything an earlier run left here is report data nobody is waiting for.
    Cleared at the start as well as the end, because the end is the part that
    does not happen when a run fails midway.
    """
    stale = privacy.sweep(output_dir) + privacy.sweep_local_queue()
    if stale:
        print(f"Cleared {len(stale)} files left by an earlier run")


def _start_run(item, output_dir: Path, started: datetime) -> tuple[RunContext, list[dict]] | None:
    """Read the trigger email and its list. Returns the run and its rows.

    The rows come back in the order of the spreadsheet, links and unusable
    cells together, each carrying the run context. Returns None when the
    trigger cannot start a run, having already failed the item with the
    business reason.
    """
    import os
    import uuid

    trigger = read_trigger(item, output_dir)
    payload = item.payload if isinstance(item.payload, dict) else {}

    attachment = trigger.attachments[0] if trigger.attachments else None
    if attachment is None:
        # A run started by hand has no attachment, which is not an error.
        fallback = payload.get("links_file") or os.environ.get("VIGIFLOW_LINKS_FILE")
        if fallback:
            attachment = Path(str(fallback))
    if attachment is None:
        print("The triggering email carried no spreadsheet.")
        item.fail("BUSINESS", code="NO_ATTACHMENT", message="No spreadsheet attached to the email")
        return None

    try:
        listed = read_links(attachment)
    except LinksError as err:
        print(f"Could not read the list: {err}")
        item.fail("BUSINESS", code="UNREADABLE_LIST", message=str(err))
        return None

    context = RunContext(
        run_id=uuid.uuid4().hex[:12],
        reply_to=trigger.reply_to or str(payload.get("reply_to") or ""),
        input_file=attachment.name,
        started_at=started.isoformat(),
        subject=trigger.subject,
        sender_name=trigger.sender_name,
        total_links=listed.rows,
    )
    if not context.reply_to:
        print("No sender address, so the report could not be emailed back.")
        item.fail(
            "BUSINESS", code="NO_REPLY_ADDRESS", message="The trigger carried no address to reply to"
        )
        return None

    print(listed.describe())
    for note in listed.skipped + trigger.notes:
        print(f"  {note}")

    # Links and problems together, back in the order of the spreadsheet, so
    # the workbook and the reply both read in the order the analyst wrote.
    entries = [(r.row, "link", r) for r in listed.reports]
    entries += [(p.row, "problem", p) for p in listed.problems]
    entries.sort(key=lambda e: e[0])

    queued = []
    for position, (row, kind, entry) in enumerate(entries, start=1):
        row_payload = {"source_row": row, "position": position, **context.to_payload()}
        if kind == "link":
            row_payload["url"] = entry.url
            row_payload["guid"] = entry.guid
        else:
            # Nothing to open, so the row passes straight through to the reply
            # rather than a browser tab being opened on whatever the cell holds.
            row_payload["problem"] = entry.detail
            row_payload["value"] = entry.value
        queued.append(row_payload)
    return context, queued


def _read_row(page, payload: dict, output_dir: Path, tally: Tally) -> dict | None:
    """Read one row of the list, and say what the reply needs to know about it.

    Returns a report, carrying its fields, or a broken link, carrying the
    reason and the path of its screenshot when there is one. Returns None for
    a row with nothing to act on, which only a malformed work item produces.
    ``page`` may be None when the row needs no browser.
    """
    row = payload.get("source_row")

    # The list reader already decided this one cannot be opened.
    if payload.get("problem"):
        print(f"  row {row}: not a VigiFlow link")
        tally.broken += 1
        return _broken(payload, str(payload["problem"]), None, NOT_A_LINK)

    url = str(payload.get("url") or "")
    if not url:
        return None

    scraped = scrape_report(page, url)
    if not scraped.ok:
        # Not an error to diagnose but an answer to report: this link does not
        # lead to a report. The picture is the evidence, and it is of an error
        # page rather than a case. Named in Spanish because it is attached to
        # the reply.
        print(f"  row {row}: not a report")
        shot = screenshot(page, output_dir / f"enlace-fila-{row}.png")
        tally.broken += 1
        return _broken(payload, NOT_A_REPORT_DETAIL, shot, LINK_NOT_A_REPORT)

    tally.read += 1
    if scraped.unopened:
        # Read, but not completely, for a reason that is not the report's.
        # Counted so the reply can say so; without this the workbook simply
        # looks complete.
        tally.partial += 1
        if scraped.blocked_by:
            tally.blockers[scraped.blocked_by] += 1
        print(f"  row {row}: read, but {len(scraped.unopened)} sections could not be opened")
    else:
        print(f"  row {row}: read")
    for name in scraped.missing:
        tally.gaps[name] += 1

    return {
        "report_id": scraped.report_id,
        "fields": _jsonable(scraped.fields),
        "unopened": scraped.unopened,
        "blocked_by": scraped.blocked_by,
        "position": payload.get("position"),
        "source_row": row,
        **{key: payload.get(key) for key in CONTEXT_KEYS},
    }


def _broken(payload: dict, detail: str, shot: Path | None, code: str) -> dict:
    """A row that is not a report, as the reply and Control Room need it."""
    return {
        "broken": True,
        "code": code,
        "detail": detail,
        "value": payload.get("value") or payload.get("url") or "",
        "position": payload.get("position"),
        "source_row": payload.get("source_row"),
        "screenshot_path": str(shot) if shot else None,
        **{key: payload.get(key) for key in CONTEXT_KEYS},
    }


def _broken_message(outcome: dict) -> str:
    template = BROKEN_MESSAGES.get(outcome.get("code"), "Row {row} could not be used")
    return template.format(row=outcome.get("source_row"))


def _reply_entry(payload: dict, path: str | None) -> dict:
    """A broken row as the reply lists it, with its screenshot if it has one."""
    entry = {
        "row": payload.get("source_row"),
        "value": payload.get("value") or "",
        "detail": payload.get("detail") or "",
        "position": payload.get("position") or 0,
    }
    if path:
        entry["screenshot"] = Path(path).name
        entry["path"] = str(path)
    return entry


def _finish_run(
    context: RunContext, rows: list[dict], broken: list[dict], output_dir: Path, finished: datetime
) -> None:
    """Write the workbook, send the reply, then delete what the run created."""
    broken.sort(key=lambda b: int(b.get("position") or 0))
    shots = [b["path"] for b in broken if b.get("path")]

    destination = None
    notes: list[str] = []
    if rows:
        destination, unknown = _write_workbook(rows, output_dir)
        if unknown:
            notes.append(_no_ev_note(unknown))
        incomplete = [r for r in rows if r.get("unopened")]
        if incomplete:
            notes.append(_incomplete_note(incomplete))
    else:
        print("No link in the list led to a report, so there is nothing to attach.")

    _reply(context, finished, destination, len(rows), broken, notes, shots)

    # Everything this run put on disk, gone now that it has been sent. The
    # spreadsheet that arrived by email is included: it is the analyst's copy
    # that matters, not the robot's.
    gone = privacy.discard([destination, output_dir / context.input_file, *shots])
    if gone:
        print(f"Removed {len(gone)} files created by this run: {', '.join(gone)}")


def _write_workbook(rows: list[dict], output_dir: Path) -> tuple[Path, int]:
    """Fill the template from the rows that were read. Returns the file."""
    # Back into the order the analyst listed them in.
    rows.sort(key=lambda r: int(r.get("position") or 0))
    records = [
        ReportRecord(report_id=r["report_id"], fields=dict(r["fields"])) for r in rows
    ]

    # Column EV counts the analyses the analyst performs, so a report the
    # clinic already assessed reads S/E and one whose assessment could not be
    # read is left blank rather than given a number it has not earned.
    ev = assign_ev_column(records, start=1)
    for record in records:
        record.fields["ev"] = ev.get(record.report_id)

    validation_date = resolve_validation_date({})
    destination = output_dir / daily_filename(validation_date)
    template = template_path(resolve_template({}))

    with ExcelTemplateWriter(
        template,
        destination,
        start_number=resolve_start_number({}),
        run=SheetRun(validation_date=validation_date),
    ) as writer:
        for record in records:
            writer.write_report(record)

    print(f"Wrote {len(records)} rows to {destination.name}")
    return destination, sum(1 for value in ev.values() if value is None)


def _incomplete_note(rows: list[dict]) -> str:
    """Say plainly that some cells are empty because of VigiFlow, not the report.

    Without this the workbook looks complete. On 14-09-2026 a notice dialog
    covered every report page, and four columns came back empty on every row
    with nothing in the reply to say so.
    """
    titles = sorted({str(r["blocked_by"]) for r in rows if r.get("blocked_by")})
    count = len(rows)
    subject = "1 fila está incompleta" if count == 1 else f"{count} filas están incompletas"
    note = (
        f"{subject}: no se pudo abrir una sección del reporte, por lo que EESS., "
        "PACIENTE, GRAVEDAD y EV. pueden estar vacíos por un motivo ajeno al reporte."
    )
    if titles:
        note += " Un aviso de VigiFlow cubría la página: " + "; ".join(titles) + "."
    return note


def _no_ev_note(count: int) -> str:
    """Say in the reply how many rows have no EV, and why."""
    subject = "1 fila no tiene" if count == 1 else f"{count} filas no tienen"
    return f"{subject} EV. porque no se pudo leer la evaluación de causalidad."


def _reply(context, finished, attachment, written, broken, notes, shots) -> None:
    """Send the summary, and say plainly in the log if it could not go."""
    import os

    body = format_summary(
        input_file=context.input_file,
        started=context.started,
        finished=finished,
        requested=context.total_links,
        written=written,
        failed=len(broken),
        rows=written,
        filename=attachment.name if attachment else None,
        notes=notes,
        broken=broken,
    )
    subject = f"Reporte de VigiFlow: {context.input_file}"
    # With a no-reply From, a Reply-To gives a person somewhere to write back
    # to. Left unset unless configured, because an unmonitored one is worse
    # than none.
    reply_to = os.environ.get("VIGIFLOW_SMTP_REPLY_TO") or None
    attachments = ([attachment] if attachment else []) + list(shots)
    try:
        sent_to = send_report(
            context.reply_to, subject, body, attachments, reply_to=reply_to
        )
        print(f"Emailed the report to {sent_to}")
    except MailError as err:
        # Nothing is deleted on this path. The workbook is still a run
        # artefact, so a run that produced a report nobody received can still
        # be delivered by hand.
        print(f"Could not email the report: {err}")
        if attachment:
            print(f"The file is still available as a run artefact: {attachment}")
        _diagnose_mail()
        raise


def _diagnose_mail() -> None:
    """Say which step of sending failed, in the same log as the failure.

    Reaching the server, encrypting and signing in fail in ways that look
    alike from the outside, and the difference decides who fixes it: the
    network, the port, or the vault. Never prints the password, only its
    shape, which is what told a 16 character App Password apart from an
    account password the one time this mattered.
    """
    from vigiflow_tasks.mailer import SmtpConfig, check_connection

    try:
        config = SmtpConfig.from_vault()
    except Exception as err:  # the vault item itself is the problem
        print(f"  could not even read the SMTP settings: {privacy.safe_message(err)}")
        return

    mode = "implicit TLS" if config.secure else "STARTTLS if offered"
    stage = check_connection(config)
    print(f"  server            {config.host}:{config.port} ({mode})")
    print(f"  account           {config.username}")
    print(f"  password from     {config.password_key or 'the environment'}: "
          f"{config.describe_password()}")
    print(f"  reach the server  {'yes' if stage['connected'] else 'NO'}")
    print(f"  encryption        {stage['starttls']}")
    print(f"  sign in           {'yes' if stage['authenticated'] else 'NO'}")
    if stage["error"]:
        print(f"  server said       {stage['error']}")


def _jsonable(fields: dict) -> dict:
    """Dates become ISO strings, so a record survives the work item queue."""
    out = {}
    for key, value in fields.items():
        out[key] = value.isoformat() if isinstance(value, (date, datetime)) else value
    return out
