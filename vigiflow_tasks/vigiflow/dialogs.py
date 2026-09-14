"""Dialogs VigiFlow puts over the page, and the one this process may close.

VigiFlow announces maintenance and similar news in a modal dialog titled
"Avisos / Información relevante". It covers the application with a backdrop,
so while it is up every click lands on the backdrop instead of the control
underneath. On 14-09-2026 that silently emptied every column that needs a
section of the report opened, EESS., PACIENTE, GRAVEDAD and EV., on every row
of a run, while the columns visible on arrival came back filled. It is shown
again on every page the application loads, so it is checked on every page.

Only that notice is closed, by the id of its own button and through the safety
guard like every other click. Any other dialog is left exactly where it is and
reported by its title, because the robot cannot know what an unknown dialog's
button does.

Dialogs stack. A link to a report that does not exist opens "El reporte no
pudo ser encontrado" on top of the notice, and a click on the notice's button
then lands on the upper dialog's backdrop. So both functions look at the
topmost dialog only: the notice is closed when it is on top, and the dialog
reported as blocking the page is the one a person would actually see. That
upper dialog is also the evidence a broken link's screenshot exists to show,
which is why it is never closed.
"""

from __future__ import annotations

import logging
import re

from vigiflow_tasks.privacy import safe_message
from vigiflow_tasks.vigiflow import locators as loc
from vigiflow_tasks.vigiflow.safety import UnsafeClick, safe_click

LOGGER = logging.getLogger(__name__)

# Several notices can be queued one behind another. More than this many in a
# row means something is reopening them, and clicking on would be a loop.
MAX_NOTICES = 5
CLICK_TIMEOUT_MS = 5_000
# A dialog's title is application text, but an unknown dialog could quote the
# report it concerns, so identifiers are masked and the length is capped.
TITLE_LIMIT = 80
REPORT_ID = re.compile(r"\bPE-[A-Z0-9]+-\d+\b")


def dismiss_notices(page, wait_ms: int = 0) -> int:
    """Close VigiFlow's notice dialogs while one is on top. Returns how many.

    ``wait_ms`` gives a notice that long to arrive, for the moment straight
    after sign-in when the application fetches its notices. Everywhere else
    the check is immediate, because it runs on every page and a wait there
    would be paid on every report.
    """
    if wait_ms:
        try:
            page.wait_for_selector(loc.NOTICE_CLOSE, state="visible", timeout=wait_ms)
        except Exception:
            return 0  # no notice today, which is the normal case

    closed = 0
    for _ in range(MAX_NOTICES):
        try:
            top = page.locator(loc.DIALOG).last
            if not top.count():
                break
            # A notice underneath another dialog cannot be clicked, and the
            # dialog on top is not ours to close, so stop here.
            button = top.locator(loc.NOTICE_CLOSE).first
            if not (button.count() and button.is_visible()):
                break
            safe_click(button, "acknowledge a VigiFlow notice", timeout=CLICK_TIMEOUT_MS)
            # The dialog animates out, and the next notice, if there is one,
            # reuses the same button id, so a short pause rather than waiting
            # for this button to disappear.
            page.wait_for_timeout(400)
            closed += 1
        except UnsafeClick as err:
            LOGGER.warning("Refused to close a notice: %s", safe_message(err))
            break
        except Exception as err:
            LOGGER.warning("Could not close a notice: %s", safe_message(err))
            break

    if closed:
        LOGGER.info("Closed %s VigiFlow notice(s)", closed)
    return closed


def blocking_dialog(page) -> str | None:
    """The title of the topmost dialog covering the page, or None if there is none."""
    try:
        dialog = page.locator(loc.DIALOG).last
        if not (dialog.count() and dialog.is_visible()):
            return None
        heading = dialog.locator(loc.DIALOG_TITLE).first
        title = heading.inner_text() if heading.count() else ""
    except Exception:
        return None
    title = REPORT_ID.sub("<report>", re.sub(r"\s+", " ", title or "").strip())
    return title[:TITLE_LIMIT] or "a dialog with no title"
