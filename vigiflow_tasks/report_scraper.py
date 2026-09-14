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
from vigiflow_tasks.vigiflow.dialogs import blocking_dialog, dismiss_notices

LOGGER = logging.getLogger(__name__)

SETTLE_MS = 20_000
# How many vaccine rows an ESAVI form is searched for. The form numbers them
# from 0 and the search stops at the first gap, so this is only a ceiling.
MAX_VACCINES = 20
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
    # Sections that could not be opened, and the title of any dialog covering
    # the page when they failed. Columns read from those sections are empty
    # for a reason that is not in the report, and the reply says so.
    unopened: list[str] = field(default_factory=list)
    blocked_by: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.report_id)

    def as_record(self) -> ReportRecord:
        return ReportRecord(report_id=self.report_id or self.url, fields=dict(self.fields))


def scrape_report(page, url: str) -> ScrapedReport:
    """Open one report and read everything the workbook needs from it."""
    from vigiflow_tasks.causality import SECTION_NAME, read_causality

    result = ScrapedReport(url=url)

    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=SETTLE_MS)
        page.wait_for_timeout(1_200)
    except Exception as err:
        result.notes.append(f"could not open: {safe_message(err)}")
        return result

    # A VigiFlow notice covers the page with a backdrop that swallows every
    # click. It is closed before anything else is read, and nothing else is.
    dismiss_notices(page)

    match = WORLDWIDE_ID.search(_body_text(page))
    if not match:
        result.notes.append("no report identifier on the page")
        result.blocked_by = blocking_dialog(page)
        return result
    result.report_id = match.group(0)

    # Vaccine adverse events live on a different form with different field
    # ids. It is recognised by a field only that form has, not by the address,
    # so a link that redirects is still read with the right rules.
    if page.locator(loc.AEFI_MARKER).count():
        return _read_aefi(page, result)

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
        result.unopened.append(loc.TAB_NOTIFIER)

    initials = None
    if _open_section(page, loc.SECTION_PATIENT):
        page.wait_for_timeout(700)
        initials = _value(page, loc.FIELD_PATIENT_INITIALS)
    else:
        result.notes.append(f"could not open {loc.SECTION_PATIENT!r}")
        result.unopened.append(loc.SECTION_PATIENT)

    causality = read_causality(page, result.report_id)
    assessed = causality.assessed if causality.matrix_found else None
    if not causality.section_found:
        result.unopened.append(SECTION_NAME)

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

    _note_missing(result, receipt, organisation, initials, drugs)
    if result.unopened:
        result.blocked_by = blocking_dialog(page)
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

    # A notice can arrive after the page settles, so it is checked again here.
    # If some other dialog is still up, every click would wait out its timeout
    # on the backdrop, so the section is reported unopened straight away.
    dismiss_notices(page)
    if blocking_dialog(page):
        return False

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


def _read_aefi(page, result: ScrapedReport) -> ScrapedReport:
    """Read an ESAVI report, which lives on a different form from an ICSR.

    VigiFlow keeps vaccine adverse events on their own form, reached by an
    /aefiform/ address instead of /dataentry/. The workbook's columns are there
    under different field ids, and the whole form is one page, so every field
    is read by id and nothing is clicked. That matters on this form beyond
    speed: its section headings carry "add" controls, and a click aimed at a
    heading has no business landing near one.

    Where an ICSR rule has an obvious counterpart, the counterpart is used.
    Where it does not, the choice is named in the comment beside it.
    """
    from vigiflow_tasks.causality import read_causality

    receipt = _date_parts(page, loc.DATE_RECEIPT_LATEST) or _date_parts(
        page, loc.DATE_RECEIPT_INITIAL
    )
    report_date = _date_parts(page, loc.AEFI_DATE_REPORT)
    # The ESAVI reporting id follows the ICSR title's convention exactly, a
    # code assigned by the establishment that ends in the report type, so it
    # fills column I and, through its suffix, column F.
    code = _value(page, loc.AEFI_REPORTING_ID)
    # The notifier's institution is the counterpart of the notifier's
    # organisation that column E reads on an ICSR. The form also names a health
    # facility, which can differ, and it is used only when the institution is
    # empty. Which of the two EESS. means on this form is for the business.
    organisation = _value(page, loc.AEFI_REPORTER_INSTITUTION) or _value(
        page, loc.AEFI_HEALTH_FACILITY
    )
    # Severity travels in an address field by agreement. On the ESAVI form it
    # has been seen in the patient's city while the notifier's address was
    # empty, so both are tried, notifier first. The vocabulary check still
    # guards against a real place name.
    severity = _severity(
        _value(page, loc.AEFI_REPORTER_CITY), _value(page, loc.AEFI_REPORTER_STATE)
    ) or _severity(_value(page, loc.AEFI_PATIENT_CITY), _value(page, loc.AEFI_PATIENT_STATE))
    # Initials only. The form also holds the patient's full name, which the
    # workbook must never carry.
    initials = _value(page, loc.AEFI_PATIENT_INITIALS)
    vaccines = _suspect_names(_aefi_vaccines(page))

    causality = read_causality(page, result.report_id, open_section=False)
    assessed = causality.assessed if causality.matrix_found else None

    result.fields = {
        "fecha_recepcion_reciente": receipt,
        "fecha_notificacion": report_date,
        "eess": organisation,
        "tipo_reporte": _type_from_title(code or "") or "ESAVI",
        "ev": None,  # numbered across the run, once every report is known
        "id_codigo": result.report_id,
        "codigo_ipress": code or result.report_id,
        "paciente": initials,
        "medicamentos_sospechosos": vaccines,
        "gravedad": severity,
        # Not written to the workbook; used to number column EV.
        "_clinic_assessed": assessed,
    }
    _note_missing(result, receipt, organisation, initials, vaccines)
    return result


def _aefi_vaccines(page) -> list[tuple]:
    """Each vaccine on an ESAVI form, as (name as reported, coded name, role)."""
    entries = []
    for index in range(MAX_VACCINES):
        name_id = loc.AEFI_VACCINE_NAME.format(index=index)
        coded_id = loc.AEFI_VACCINE_CODED.format(index=index)
        try:
            if not (page.locator(name_id).count() or page.locator(coded_id).count()):
                break
        except Exception:
            break
        entries.append((
            _value(page, name_id),
            _value(page, coded_id),
            _value(page, loc.AEFI_VACCINE_ROLE.format(index=index)),
        ))
    return entries


def _suspect_names(entries) -> list[str]:
    """The suspect products' names, in form order and without repeats.

    The name as reported is preferred, because that is the name the ICSR
    sidebar shows. A product whose role is recorded and is not suspect is left
    out, since the columns are for suspect products; one with no role recorded
    is kept rather than guessed away.
    """
    names: list[str] = []
    for reported, coded, role in entries:
        if role and "sospech" not in fold(role):
            continue
        name = (reported or coded or "").strip()
        if name and "falta el nombre" not in fold(name) and name not in names:
            names.append(name)
    return names


def _note_missing(result: ScrapedReport, receipt, organisation, initials, drugs) -> None:
    """Record which of the fields the run summary counts came back empty."""
    for name, value in (
        ("fecha_recepcion_reciente", receipt),
        ("eess", organisation),
        ("paciente", initials),
        ("medicamentos_sospechosos", drugs),
    ):
        if not value:
            result.missing.append(name)
