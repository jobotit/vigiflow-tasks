"""Reads one report from its own page, without the export.

The email-driven process gives the robot a list of links and nothing else, so
each report has to yield its whole row on its own. The export is not available
here: it only ever contains what some filter selected, and an on-demand list
can name anything.

The page is used rather than the PDF. The PDF has every label, but it renders
the notifier block and the medicament table as a block of labels followed by a
block of values, so reading them means counting positions. On the page each
field is a labelled control with a value beside it, which is far steadier.

Reading only. Sections are opened by name, every click passes the safety
guard, nothing is typed, and no control that saves, deletes or clears is
touched.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from vigiflow_tasks.models import ReportRecord
from vigiflow_tasks.privacy import safe_message
from vigiflow_tasks.vigiflow import locators as loc

LOGGER = logging.getLogger(__name__)

SETTLE_MS = 20_000
# Set VIGIFLOW_SCRAPE_DEBUG to have each report report the labels it saw,
# which is how a field that stops being found gets diagnosed.
DEBUG = bool(__import__("os").environ.get("VIGIFLOW_SCRAPE_DEBUG"))
WORLDWIDE_ID = re.compile(r"\bPE-[A-Z0-9]+-\d+\b")

# Sections of the report that have to be opened to read their fields.
SECTION_REPORT = "Información del reporte"
SECTION_PATIENT = "Paciente"
TAB_NOTIFIER = "Información del notificador"

# Labels as the page writes them, matched with accents stripped.
LABEL_TITLE = "titulo del reporte"
LABEL_RECEIPT_LATEST = "fecha de recepcion mas reciente"
LABEL_RECEIPT_INITIAL = "fecha de recepcion inicial"
LABEL_REPORT_DATE = "fecha del reporte"
LABEL_INITIALS = "iniciales"
LABEL_NOTIFIER_ORG = "organizacion"
LABEL_CITY = "ciudad (sub-distrito)"
LABEL_STATE = "estado o provincia"

SEVERITY_TERMS = ("leve", "moderado", "moderada", "grave", "severa")
REPORT_TYPES = ("ram", "tab", "vih", "esavi")


class ScrapeError(RuntimeError):
    """A report could not be read."""


def fold(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped).strip().lower()


@dataclass
class ScrapedReport:
    """One report, and how completely it could be read."""

    url: str
    report_id: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.report_id)

    def as_record(self) -> ReportRecord:
        return ReportRecord(report_id=self.report_id or self.url, fields=dict(self.fields))


def scrape_report(page, url: str) -> ScrapedReport:
    """Open one report and read everything the workbook needs from it."""
    from vigiflow_tasks.causality import read_causality

    result = ScrapedReport(url=url)

    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=SETTLE_MS)
        page.wait_for_timeout(1_200)
    except Exception as err:
        result.notes.append(f"could not open: {safe_message(err)}")
        return result

    match = WORLDWIDE_ID.search(_body_text(page))
    if not match:
        result.notes.append("no report identifier on the page")
        return result
    result.report_id = match.group(0)

    # The medicament names are in the left sidebar, which is on screen from
    # the moment the report opens.
    drugs = _sidebar_drugs(page)

    # The report section is what opens first, and the notifier tab sits at the
    # foot of it. Both are read before navigating anywhere, because opening
    # another section replaces that part of the page.
    title = _value(page, loc.FIELD_TITLE)
    receipt = _date_parts(page, loc.DATE_RECEIPT_LATEST) or _date_parts(
        page, loc.DATE_RECEIPT_INITIAL
    )
    report_date = _date_parts(page, loc.DATE_REPORT)

    organisation = severity = None
    if _open_section(page, loc.TAB_NOTIFIER):
        page.wait_for_timeout(700)
        organisation = _value(page, loc.FIELD_NOTIFIER_ORG)
        severity = _severity(
            _value(page, loc.FIELD_NOTIFIER_CITY),
            _value(page, loc.FIELD_NOTIFIER_STATE),
        )
    else:
        result.notes.append(f"could not open {loc.TAB_NOTIFIER!r}")

    initials = None
    if _open_section(page, loc.SECTION_PATIENT):
        page.wait_for_timeout(700)
        initials = _value(page, loc.FIELD_PATIENT_INITIALS)
    else:
        result.notes.append(f"could not open {loc.SECTION_PATIENT!r}")

    causality = read_causality(page, result.report_id)
    assessed = causality.assessed if causality.matrix_found else None

    result.fields = {
        "fecha_recepcion_reciente": receipt,
        "fecha_notificacion": report_date,
        "eess": organisation,
        "tipo_reporte": _type_from_title(title or ""),
        "ev": None,  # numbered across the run, once every report is known
        "id_codigo": result.report_id,
        "codigo_ipress": title or result.report_id,
        "paciente": initials,
        "medicamentos_sospechosos": drugs,
        "gravedad": severity,
        # Not written to the workbook; used to number column EV.
        "_clinic_assessed": assessed,
    }

    for name, value in (
        ("fecha_recepcion_reciente", receipt),
        ("eess", organisation),
        ("paciente", initials),
        ("medicamentos_sospechosos", drugs),
    ):
        if not value:
            result.missing.append(name)
    return result


def _value(page, selector: str) -> str | None:
    """One field's value, by its id."""
    try:
        element = page.locator(selector).first
        if not element.count():
            return None
        text = (element.input_value() if element.count() else "") or ""
    except Exception:
        try:
            text = page.locator(selector).first.inner_text()
        except Exception:
            return None
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text or None


def _date_parts(page, stem: str) -> date | None:
    """A date written as three boxes sharing an id stem.

    Every date on this form is three inputs, ``<stem>Day``, ``<stem>Month``
    and ``<stem>Year``. An empty box means the date was never filled in, so
    the result is None rather than a guess.
    """
    parts = []
    for suffix in ("Day", "Month", "Year"):
        value = _value(page, f"#{stem}{suffix}")
        if not value:
            return None
        parts.append(value)
    try:
        day, month, year = (int(p) for p in parts)
        return date(year, month, day)
    except (ValueError, TypeError):
        # The parts themselves are report data, so only the field is named.
        LOGGER.warning("Unreadable date in %s", stem)
        return None


def _body_text(page) -> str:
    try:
        return page.locator("body").inner_text()
    except Exception:
        return ""


def _open_section(page, name: str) -> bool:
    from vigiflow_tasks.vigiflow.safety import UnsafeClick, safe_click

    for selector in (
        f"[role=tab]:text-is({name!r})",
        f"[role=tab]:has-text({name!r})",
        f"text={name}",
    ):
        try:
            element = page.locator(selector).first
            if not (element.count() and element.is_visible()):
                continue
            safe_click(element, f"open {name!r}", timeout=SETTLE_MS)
            return True
        except UnsafeClick as err:
            LOGGER.warning("Refused to open %r: %s", name, safe_message(err))
            return False
        except Exception:
            continue
    return False


def _sidebar_drugs(page) -> list[str]:
    """The suspect drugs, read from the report's own left-hand navigation.

    The sidebar lists one entry per medicament under a MEDICAMENTO heading,
    which is both the shortest path to them and the order the report itself
    uses. An entry reading "Falta el nombre del medicamento" is VigiFlow
    saying the drug was never named, so it is dropped rather than written into
    the workbook as if it were a drug.
    """
    try:
        names = page.evaluate(
            r"""() => {
                const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
                const fold = (s) => clean(s).normalize('NFKD')
                    .replace(/[̀-ͯ]/g, '').toLowerCase();
                const items = [...document.querySelectorAll(
                    'mat-list-item, .mat-list-item, [role=listitem], nav li, nav a')];
                const texts = items.map(n => clean(n.innerText)).filter(Boolean);
                const start = texts.findIndex(t => fold(t) === 'medicamento');
                if (start < 0) return [];
                const stop = new Set([
                    'reaccion', 'analisis y procedimientos', 'evaluacion',
                    'vista general', 'paciente', 'informacion del reporte']);
                const out = [];
                for (let i = start + 1; i < texts.length; i++) {
                    if (stop.has(fold(texts[i]))) break;
                    out.push(texts[i]);
                }
                return out;
            }"""
        )
    except Exception as err:
        LOGGER.warning("Could not read the medicament list: %s", safe_message(err))
        return []

    drugs: list[str] = []
    for name in names or []:
        cleaned = re.sub(r"\s+", " ", str(name)).strip()
        if not cleaned or "falta el nombre" in fold(cleaned):
            continue
        if cleaned not in drugs:
            drugs.append(cleaned)
    return drugs


def _severity(city: Any, state: Any) -> str | None:
    """LEVE / MODERADO / GRAVE out of the notifier's address fields.

    VigiFlow has no severity field, so by a standing agreement the notifiers
    put it in the address. Those fields also hold real places, so only the
    vocabulary is accepted.
    """
    for candidate in (city, state):
        folded = fold(candidate)
        if not folded:
            continue
        for term in SEVERITY_TERMS:
            if folded == term or re.search(rf"\b{term}\b", folded):
                return term.upper()
    return None


def _type_from_title(title: str) -> str | None:
    """RAM / TAB / VIH / ESAVI, read off the end of the report title."""
    for word in reversed(fold(title).replace("-", " ").split()):
        if word in REPORT_TYPES:
            return word.upper()
    return None


def screenshot(page, destination) -> Path | None:
    """Photograph the current page, to show why a link was rejected.

    Only ever called for a page that turned out not to be a report, so what it
    captures is an error page rather than a case. That is the reason automatic
    screenshots are off: this is the one picture worth keeping, and it is taken
    deliberately.

    Returns None rather than raising. A link that cannot even be photographed
    is still a link worth reporting.
    """
    destination = Path(destination)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(destination), full_page=False)
    except Exception as err:
        LOGGER.warning("Could not capture the page: %s", safe_message(err))
        return None
    return destination if destination.exists() else None
