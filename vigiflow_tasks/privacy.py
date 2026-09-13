"""Keeping what the robot reads out of the run logs, and off the disk.

A report page carries the whole case: the narrative, the dates, the drugs, the
notifier and the patient. The finished workbook carries far less, and the
business treats that as not sensitive, but everything the robot reads on the
way there is.

The danger is not the `print` statements, which are easy to see. It is that
robocorp-log instruments this package automatically and records the arguments
and return values of every call it makes. `_body_text` returns an entire report
page as a string, so by default that page lands in `log.html` in full. This
module closes that.

Two rules, applied at the top of every task:

    Variables are never logged. The call graph still is, so a failure is still
    locatable; what flowed through it is not recorded.

    Messages are trimmed to one short line. Playwright puts the text of
    matching elements into its errors, and those dumps run to many lines, so
    keeping only the first line removes most of what could ride along into a
    log, a Control Room exception or an email.

Neither rule helps if a picture of the page is taken instead, which is why
automatic screenshots are off in `vigiflow.browser_client`. The only
screenshots this process takes are of pages that turned out not to be reports.

The last route is the disk. The workbook, the spreadsheet that arrived by
email and the screenshots all sit in the artefacts directory after a run, so
`discard` removes them once the reply has been sent and `sweep` clears
anything an earlier run left behind. Neither touches `log.html`, which the
framework owns and which the rules above keep free of report data.

The work item queue is the one store this module cannot finish the job on. A
scraped row travels to the reporter as a work item payload, and in Control
Room that payload is the platform's storage, with its own retention setting.
`sweep_local_queue` clears it for local runs, where it is just a folder of
JSON, and does nothing anywhere else.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# One short line is enough to say what went wrong. Anything longer is either a
# stack of selectors or a dump of the page.
MESSAGE_LIMIT = 160


def no_data_in_logs():
    """Stop robocorp-log recording the values passing through this package.

    Used as a context manager around a whole task. Method calls are still
    logged, so `log.html` still shows where a run failed; only the values are
    withheld.

    Degrades to doing nothing when robocorp-log is absent, which is how the
    unit tests run without the task framework installed.
    """
    try:
        from robocorp import log
    except ImportError:  # pragma: no cover - present in every real run
        return contextlib.nullcontext()
    return log.suppress_variables()


def safe_message(err: BaseException | str, limit: int = MESSAGE_LIMIT) -> str:
    """One short line describing a failure, with no page content in it.

    Playwright reports a strict-mode violation by listing the elements that
    matched, with their text. That text is patient data. Keeping the first
    line only, capped, removes it while leaving the part that says what kind
    of failure it was.
    """
    text = str(err).strip()
    first = text.splitlines()[0].strip() if text else ""
    first = re.sub(r"\s+", " ", first)
    if len(first) > limit:
        first = first[:limit].rstrip() + "..."
    if isinstance(err, BaseException):
        name = type(err).__name__
        return f"{name}: {first}" if first else name
    return first


# What a run leaves in the artefacts directory. Extensions rather than names,
# because the workbook is named for the day and the screenshots for the row.
# Deliberately excludes the framework's own files: log.html and the .robolog
# are written as the process exits and are not ours to delete.
RUN_DATA_SUFFIXES = (".xlsx", ".xlsm", ".xls", ".csv", ".pdf", ".png")


def discard(paths) -> list[str]:
    """Delete the files a run created, and say which went.

    Called once the reply has been sent, so the data the run handled does not
    outlive the run. A file that is already gone is not an error; a file that
    will not go is reported and skipped, because failing here would fail a run
    whose actual work is finished and delivered.
    """
    removed: list[str] = []
    for candidate in paths:
        if not candidate:
            continue
        path = Path(candidate)
        try:
            if path.is_file():
                path.unlink()
                removed.append(path.name)
        except OSError as err:
            LOGGER.warning("Could not remove %s: %s", path.name, safe_message(err))
    return removed


def sweep(directory) -> list[str]:
    """Clear run data an earlier run left behind.

    Run at the start rather than trusted to the end, because the end is the
    part that does not happen when a run fails midway. Only the data
    extensions are touched, so the environment files and the framework's logs
    are left alone.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    stale = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in RUN_DATA_SUFFIXES]
    return discard(stale)


def sweep_local_queue() -> list[str]:
    """Clear the local work item store at the start of a run.

    Work item payloads carry the scraped rows, so on a developer's machine
    they are report data sitting in a folder. Only the FileAdapter keeps them
    there; in Control Room the queue belongs to the platform and its retention
    is a workspace setting, not something a task should reach into.

    Guarded on the directory's name so that a differently configured adapter
    path cannot turn this into a delete of something else.
    """
    configured = os.environ.get("RC_WORKITEM_OUTPUT_PATH") or ""
    if not configured:
        return []
    # devdata/work-items-out/<step>/work-items.json
    root = Path(configured).resolve().parent.parent
    if root.name != "work-items-out" or not root.is_dir():
        return []
    removed = [path.name for path in root.rglob("*") if path.is_file()]
    shutil.rmtree(root, ignore_errors=True)
    return removed
