"""Refusing to click anything that is not safe to click.

The report page carries controls that create records, reassign cases, delete
reports and write the data entry form, sitting next to the ones this
automation legitimately uses. A selector that drifts one control either way
does real damage silently.

So every click in this package goes through :func:`safe_click`, which reads
the element's own id and visible label and refuses anything on the list below.
It reads the element rather than trusting the selector that found it, because
the selector is exactly what goes wrong.
"""

from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)


class UnsafeClick(RuntimeError):
    """Refused to click something that is not a filter control."""


# Controls that must never be clicked by automation. Some
# create records, some change other people's data, and some alter the saved
# filters this account relies on. The guard below refuses them by id or by
# visible text, so a selector that drifts onto one of them fails loudly
# instead of quietly doing damage.
FORBIDDEN_IDS = frozenset(
    {
        "delete",             # Eliminar, deletes the report outright
        "save",               # Guardar, writes the data entry form
        "delegateTo",         # reassigns the report to another organisation
        "statusToggle",       # changes the report's state
        "newIcsr",            # Nuevo reporte, creates a new ICSR
        "newAefi",            # ESAVI nuevo, creates a new AEFI report
        "saveFilterBtn",      # Guardar, overwrites the account's saved filters
        "exportToggle",       # Descargar, starts a download
        "vigilyze",           # leaves the application
        "headerMenu",         # account menu, holds sign out
    }
)
FORBIDDEN_ID_PREFIXES = (
    "assignedTo_",            # reassigns a report to someone else
    "openIcsrResultToggle_",  # per-row action menu
    "icsr_",                  # per-row selection checkbox
)
FORBIDDEN_TEXTS = (
    "nuevo reporte",
    "esavi nuevo",
    "guardar",
    "cerrar sesión",
    "cerrar sesion",
    "eliminar",
    "borrar",
    # Seen on the report data entry form. "Vaciar los campos" empties a whole
    # section, and "Agregar" adds a row to one. Neither is navigation.
    "vaciar",
    "agregar",
    # The form renders Material icons as text, so an inline remove control
    # reads literally "delete". Seen beside "Otros problemas relacionados al
    # uso del medicamento" in the field inventory.
    "delete",
    "enviar",
    "submit",
    "delegar",
)


def assert_safe(element, where: str = "", allow: tuple[str, ...] = ()) -> None:
    """Refuse to click anything this automation has no business clicking.

    Reads the element's own identity rather than trusting the selector that
    found it, because the selector is exactly what goes wrong.

    ``allow`` names ids that this one call may click despite the denylist. It
    exists so an investigation can reach a control such as the export button
    without weakening the guard for everything else, and so that every such
    exception is visible at the call site.
    """
    try:
        element_id = (element.get_attribute("id") or "").strip()
        text = (element.inner_text() or "").strip().lower()
    except Exception:
        return  # cannot inspect it; the caller's own selector has to stand

    if element_id and element_id in allow:
        LOGGER.warning(
            "Clicking #%s, which is normally refused, because the caller "
            "explicitly allowed it (%s)", element_id, where or "no reason given"
        )
        return

    if element_id in FORBIDDEN_IDS or element_id.startswith(FORBIDDEN_ID_PREFIXES):
        raise UnsafeClick(
            f"Refusing to click #{element_id}{f' ({where})' if where else ''}: "
            "it changes data rather than navigating."
        )

    for forbidden in FORBIDDEN_TEXTS:
        if forbidden in text:
            raise UnsafeClick(
                f"Refusing to click a control reading {text[:40]!r}"
                f"{f' ({where})' if where else ''}: it changes data rather than navigating."
            )


def safe_click(element, where: str = "", allow: tuple[str, ...] = (), **kwargs) -> None:
    """Click, but only after confirming the target only navigates."""
    assert_safe(element, where, allow)
    element.click(**kwargs)
