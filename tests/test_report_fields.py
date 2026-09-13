"""The business rules that turn a report page into one row of the workbook.

These are the rules that were agreed with the people who run the process
rather than read off the screen, so they are the ones worth pinning down.
None of them needs a browser.
"""

import pytest

from vigiflow_tasks.excel.template_writer import _as_digits
from vigiflow_tasks.report_scraper import WORLDWIDE_ID, _severity, _type_from_title


# -- the report's own identifier -------------------------------------------


@pytest.mark.parametrize(
    "page_text,expected",
    [
        ("Reporte PE-DIGEMID-399999001 abierto", "PE-DIGEMID-399999001"),
        ("PE-DIGEMID-399999001\nPaciente", "PE-DIGEMID-399999001"),
        ("  PE-EXAMPLE-00009  ", "PE-EXAMPLE-00009"),
    ],
)
def test_the_identifier_is_read_whole_from_the_page(page_text, expected):
    """The sender part varies, so stripping it would merge distinct reports."""
    match = WORLDWIDE_ID.search(page_text)
    assert match and match.group(0) == expected


def test_a_page_without_an_identifier_yields_nothing():
    """Better no report than the wrong one: the scraper fails the work item."""
    assert WORLDWIDE_ID.search("Sesión expirada") is None


# -- column H, the numeric part of the identifier --------------------------


@pytest.mark.parametrize(
    "world_wide,cell",
    [
        ("PE-DIGEMID-399999001", 399999001),
        ("PE-EXAMPLE-00009", "00009"),
        ("no-digits-here", "no-digits-here"),
    ],
)
def test_column_h_keeps_leading_zeros(world_wide, cell):
    """Most ids are numbers, but 00009 written as a number is a different id.

    So a value with a leading zero is written as text, which is the only way
    Excel will keep it, and everything else stays a number to match the file
    the business produces by hand.
    """
    assert _as_digits(world_wide) == cell


# -- column P, severity out of the notifier's address ----------------------


@pytest.mark.parametrize(
    "city,state,expected",
    [
        ("LEVE", "Lima", "LEVE"),
        ("Lima", "GRAVE", "GRAVE"),
        ("reaccion moderada", "Lima", "MODERADA"),
        ("Lima", "Lima", None),
        ("", "", None),
    ],
)
def test_severity_is_read_from_the_address_field(city, state, expected):
    """VigiFlow has no severity field, so by standing agreement it goes here.

    Those fields also hold real places, so only the agreed vocabulary counts;
    anything else leaves the cell empty rather than guessing.
    """
    assert _severity(city, state) == expected


# -- column F, the report type off the title -------------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Notificación de sospecha RAM", "RAM"),
        ("Reporte ESAVI", "ESAVI"),
        ("Caso TAB", "TAB"),
        ("Seguimiento VIH", "VIH"),
        ("Reporte sin tipo", None),
        ("", None),
    ],
)
def test_the_report_type_comes_from_the_title(title, expected):
    assert _type_from_title(title) == expected
