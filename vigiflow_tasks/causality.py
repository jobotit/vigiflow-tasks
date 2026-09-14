"""Whether a report carries a causality assessment.

Column EV counts the analyses the analyst performs, and the rule runs
opposite to the obvious reading. When the notifying clinic has already filled
in its causality assessment, the analyst has nothing to analyse and the cell
reads "S/E". When the clinic left it empty, the analyst does the analysis and
the cell takes the next sequential number.

This is the one field the export cannot supply. The causality matrix, which
relates each suspect drug to each reaction, appears in no sheet of the export,
so the only way to know is to look at the report's Evaluación section.

Reading only. The section is opened by its name and the matrix is inspected;
nothing is typed and no control that saves is pressed.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from vigiflow_tasks.privacy import safe_message


LOGGER = logging.getLogger(__name__)

NOT_ASSESSED = "S/E"
SECTION_NAME = "Evaluación"
SETTLE_MS = 15_000

# The Evaluación section holds two kinds of dropdown, and only one of them is
# the judgement.
#
#   internalMethodOfAssessment_*   the method, always reading "WHO-UMC
#                                  Causality" whether or not anyone has judged
#                                  anything. Counting these marks every report
#                                  as assessed, which an earlier version did.
#   internalResultOfAssessment_*   the verdict for one drug and reaction pair:
#                                  Probable, Posible, Cierta and so on. Empty
#                                  until somebody makes the call.
#
# So the question "has this been assessed" is answered only by the result
# dropdowns, and only when one of them carries a value.
RESULT_MARKER = "resultofassessment"
METHOD_MARKER = "methodofassessment"

# What a dropdown shows when nothing has been chosen.
EMPTY_MARKERS = {"", "-", "--", "seleccionar", "select", "none", "null"}
# The method text, which is never a verdict even if it lands in a result cell.
NOT_A_VERDICT = {"who-umc causality", "who umc causality"}


def fold(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped).strip().lower()


@dataclass
class Causality:
    """What the Evaluación section says about one report."""

    report_id: str
    section_found: bool = False
    matrix_found: bool = False
    cells: int = 0
    filled: int = 0
    values: list[str] | None = None
    detail: list = None
    note: str = ""

    @property
    def assessed(self) -> bool:
        """True when the clinic has judged at least one drug and reaction pair.

        Assessed means the analyst does nothing, so this leads to "S/E" in
        column EV, not to a number.
        """
        return self.filled > 0


def read_causality(page, report_id: str = "", open_section: bool = True) -> Causality:
    """Report whether causality was assessed, opening the Evaluación section first.

    ``open_section=False`` is for the ESAVI form, which shows every section at
    once, so there is nothing to open and nothing should be clicked.
    """
    result = Causality(report_id=report_id)

    if open_section and not _open_section(page):
        result.note = f"could not open {SECTION_NAME!r}"
        return result
    result.section_found = True
    page.wait_for_timeout(800)

    matrix = _read_matrix(page)
    if not matrix:
        result.note = "no dropdowns in the Evaluación section"
        return result

    result.matrix_found = matrix["cells"] > 0 or matrix.get("methods", 0) > 0
    result.cells = matrix["cells"]
    result.filled = matrix["filled"]
    result.values = matrix["values"][:6] or None
    result.detail = matrix.get("detail") or []
    return result


def _open_section(page) -> bool:
    from vigiflow_tasks.vigiflow.dialogs import blocking_dialog, dismiss_notices
    from vigiflow_tasks.vigiflow.safety import UnsafeClick, safe_click

    # Same reasoning as the report scraper: close a VigiFlow notice, and do not
    # wait out click timeouts behind any other dialog.
    dismiss_notices(page)
    if blocking_dialog(page):
        return False

    for selector in (f"text={SECTION_NAME}", f"[role=tab]:text-is({SECTION_NAME!r})"):
        try:
            element = page.locator(selector).first
            if not (element.count() and element.is_visible()):
                continue
            safe_click(element, f"open {SECTION_NAME}", timeout=SETTLE_MS)
            return True
        except UnsafeClick as err:
            LOGGER.warning("Refused: %s", safe_message(err))
            return False
        except Exception:
            continue
    return False


def _read_matrix(page) -> dict[str, Any] | None:
    """Read the drug against reaction grid in the causality panel.

    Each cell of the grid is a dropdown, so an assessment means at least one
    dropdown carries a value. The grid is found by walking out from the
    dropdowns themselves rather than by hunting for the panel's heading: the
    heading text is long, accented and easy to miss, and an earlier version
    that looked for it found nothing at all.
    """
    try:
        return page.evaluate(
            r"""([emptyMarkers, notAVerdict, resultMarker, methodMarker]) => {
                const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
                const vis = (n) => {
                    const r = n.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                };
                const selects = [...document.querySelectorAll('mat-select, select')]
                    .filter(vis);

                const rowLabel = (n) => {
                    let el = n;
                    for (let i = 0; i < 6 && el; i++) {
                        el = el.parentElement;
                        if (!el) break;
                        const cells = el.querySelectorAll('td, th, .mat-cell, div');
                        for (const c of cells) {
                            const t = clean(c.innerText);
                            if (t && t.length < 60 && !c.querySelector('mat-select, select')) {
                                return t;
                            }
                        }
                    }
                    return '';
                };

                const cells = [];
                for (const s of selects) {
                    const id = (s.id || '').toLowerCase();
                    cells.push({
                        value: clean(s.innerText || s.value || '').slice(0, 40),
                        label: rowLabel(s).slice(0, 40),
                        id: s.id || '',
                        isResult: id.includes(resultMarker),
                        isMethod: id.includes(methodMarker),
                    });
                }
                const results = cells.filter(c => c.isResult);
                let filled = 0;
                const values = [];
                for (const c of results) {
                    const bare = c.value.toLowerCase();
                    if (c.value && !emptyMarkers.includes(bare) && !notAVerdict.includes(bare)) {
                        filled += 1;
                        values.push(c.value);
                    }
                }
                return {
                    cells: results.length,
                    filled,
                    values,
                    methods: cells.filter(c => c.isMethod).length,
                    detail: cells.slice(0, 10),
                };
            }""",
            [sorted(EMPTY_MARKERS), sorted(NOT_A_VERDICT), RESULT_MARKER, METHOD_MARKER],
        )
    except Exception as err:
        LOGGER.warning("Could not read the causality matrix: %s", safe_message(err))
        return None


def assign_ev_numbers(
    records: list, clinic_assessed_ids: set[str], start: int = 1
) -> dict[str, Any]:
    """Fill column EV, which counts the analyses the analyst has to perform.

    The rule runs opposite to the obvious reading. When the notifying clinic
    has already filled in its causality assessment, the analyst has nothing to
    analyse and the cell reads "S/E". When the clinic left it empty, the
    analyst does the analysis and the cell takes the next number.

    So the correlative skips the S/E rows rather than numbering them, and runs
    in processing order, which is oldest first. The business treats the number
    as arbitrary, so it starts at 1 unless told otherwise.
    """
    out: dict[str, Any] = {}
    next_number = start
    for record in records:
        report_id = getattr(record, "report_id", None) or record.get("report_id")
        if report_id in clinic_assessed_ids:
            out[report_id] = NOT_ASSESSED
        else:
            out[report_id] = next_number
            next_number += 1
    return out


# What the scraper records about the clinic's own assessment: True, False, or
# None when the Evaluación section could not be read at all.
CLINIC_ASSESSED_FIELD = "_clinic_assessed"


def assign_ev_column(records: list, start: int = 1) -> dict[str, Any]:
    """Fill column EV for a whole run, from what each report's scrape found.

    Three states, because there are three:

        the clinic assessed it       "S/E", the analyst has nothing to analyse
        the clinic left it empty     the next number, the analyst does it
        it could not be read         blank

    The third case is the one worth stating. An unread report has no verified
    answer, and writing a number into it would claim the analyst did work
    nobody checked. It still consumes its number rather than closing the gap,
    so the rows below keep the numbers they would have had either way.
    """
    assessed = {r.report_id for r in records if r.fields.get(CLINIC_ASSESSED_FIELD) is True}
    unknown = {r.report_id for r in records if r.fields.get(CLINIC_ASSESSED_FIELD) is None}
    numbers = assign_ev_numbers(records, assessed, start=start)
    return {
        r.report_id: (None if r.report_id in unknown else numbers.get(r.report_id))
        for r in records
    }
