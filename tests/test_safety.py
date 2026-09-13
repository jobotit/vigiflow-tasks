"""The click guard, tested without a browser.

These matter more than most: the guard is what stands between a drifting
selector and a button that creates a report, reassigns a case, or overwrites
the account's saved filters.
"""

import pytest

from vigiflow_tasks.vigiflow.safety import UnsafeClick, assert_safe


class FakeElement:
    """Enough of a Playwright locator for the guard to inspect."""

    def __init__(self, element_id: str = "", text: str = ""):
        self._id = element_id
        self._text = text

    def get_attribute(self, name):
        return self._id if name == "id" else None

    def inner_text(self):
        return self._text


@pytest.mark.parametrize(
    "element_id",
    [
        "newIcsr",        # creates a new report
        "newAefi",        # creates a new AEFI report
        "saveFilterBtn",  # overwrites the saved filters
        "exportToggle",   # starts a download
        "headerMenu",     # holds sign out
        "vigilyze",       # leaves the application
    ],
)
def test_dangerous_buttons_are_refused_by_id(element_id):
    with pytest.raises(UnsafeClick):
        assert_safe(FakeElement(element_id=element_id))


@pytest.mark.parametrize(
    "element_id",
    ["assignedTo_0", "assignedTo_17", "openIcsrResultToggle_3", "icsr_11-input"],
)
def test_per_row_controls_are_refused(element_id):
    """Row controls reassign cases or select records. None are filter controls."""
    with pytest.raises(UnsafeClick):
        assert_safe(FakeElement(element_id=element_id))


@pytest.mark.parametrize(
    "text",
    ["Nuevo reporte", "add\nESAVI nuevo", "save\nGuardar", "Cerrar sesión", "Eliminar"],
)
def test_dangerous_buttons_are_refused_by_their_text(text):
    """An id can be absent or change. The visible label is the second net."""
    with pytest.raises(UnsafeClick):
        assert_safe(FakeElement(text=text))


@pytest.mark.parametrize(
    "element_id,text",
    [
        ("searchIcsrsParametersComponentSearch", "search\nAplicar filtro"),
        ("searchIcsrsParametersComponentClear", "Limpiar todos los filtros"),
        ("reportFiltersTab", "Reporte"),
        ("Status_0_0-input", ""),
        ("delegatedToOrganisationSelect", ""),
        ("mat-expansion-panel-header-0", "Filtro avanzado"),
        ("", "filter_alt\nFiltro"),
    ],
)
def test_filter_controls_are_allowed(element_id, text):
    assert_safe(FakeElement(element_id=element_id, text=text))


def test_clear_filters_is_allowed_despite_containing_a_forbidden_word():
    """'Limpiar todos los filtros' is a filter control and must stay clickable.

    It is listed as an exception because a naive substring check on words like
    'borrar' or 'eliminar' would be tempting to widen until it catches this.
    """
    assert_safe(FakeElement(element_id="searchIcsrsParametersComponentClear",
                            text="close\nLimpiar todos los filtros"))


def test_an_element_that_cannot_be_inspected_is_not_blocked():
    """The guard must not break a legitimate click when the DOM read fails."""

    class Unreadable:
        def get_attribute(self, name):
            raise RuntimeError("detached")

        def inner_text(self):
            raise RuntimeError("detached")

    assert_safe(Unreadable())


def test_the_guard_names_what_it_refused():
    with pytest.raises(UnsafeClick, match="newIcsr"):
        assert_safe(FakeElement(element_id="newIcsr"), where="open Filtro")


# -- the explicit exception ------------------------------------------------


def test_a_named_exception_is_allowed_through():
    """An investigation can reach one control without disarming the guard."""
    assert_safe(FakeElement(element_id="exportToggle"), allow=("exportToggle",))


def test_the_exception_covers_only_what_it_names():
    with pytest.raises(UnsafeClick):
        assert_safe(FakeElement(element_id="newIcsr"), allow=("exportToggle",))


def test_the_exception_does_not_disarm_the_text_rule():
    """An allowed id still cannot smuggle in a differently labelled control."""
    with pytest.raises(UnsafeClick):
        assert_safe(FakeElement(element_id="", text="Nuevo reporte"), allow=("exportToggle",))


# -- the report toolbar ----------------------------------------------------


@pytest.mark.parametrize(
    "element_id,text",
    [
        ("delete", "delete Eliminar"),
        ("save", "save Guardar"),
        ("delegateTo", "Delegar a organización"),
        ("statusToggle", "Abierto"),
    ],
)
def test_the_report_toolbar_destructive_controls_are_refused(element_id, text):
    """Descargar sits between Eliminar and Guardar on the report toolbar.

    A selector that drifts one control either way deletes a pharmacovigilance
    record or writes the data entry form, so both are refused by id and by
    label.
    """
    with pytest.raises(UnsafeClick):
        assert_safe(FakeElement(element_id=element_id, text=text))


@pytest.mark.parametrize(
    "element_id,text",
    [
        ("toolbarMoreMenu", "download Descargar"),
        ("maskedPdf", "picture_as_pdf PDF enmascarado"),
        ("unmaskedPdf", "picture_as_pdf PDF completo"),
    ],
)
def test_the_pdf_downloads_are_allowed(element_id, text):
    assert_safe(FakeElement(element_id=element_id, text=text))


@pytest.mark.parametrize(
    "text",
    ["Vaciar los campos", "Agregar", "Enviar", "Delegar a organización"],
)
def test_form_modifying_buttons_are_refused(text):
    """The report form carries controls that clear or extend a section.

    Walking the report to read it must never touch these, so they are refused
    by label the same way Guardar and Eliminar are.
    """
    with pytest.raises(UnsafeClick):
        assert_safe(FakeElement(text=text))


@pytest.mark.parametrize(
    "text",
    [
        "Información del reporte",
        "Paciente",
        "Caso narrativo e información adicional",
        "Análisis y procedimientos",
        "Evaluación",
        "Vista general",
        "Notas",
        "Documentos",
    ],
)
def test_section_navigation_stays_allowed(text):
    """Reading the report means moving between its sections, which is safe."""
    assert_safe(FakeElement(text=text))


def test_the_inline_delete_icon_is_refused():
    """The form renders icons as text, so a remove control reads "delete".

    One sits inline beside a medicament field. It carries no helpful id, so
    the label is the only thing standing between a drifting selector and a
    removed row.
    """
    with pytest.raises(UnsafeClick):
        assert_safe(FakeElement(text="delete"))
