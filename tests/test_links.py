"""Reading the analyst's list of report links.

The rule that matters here is that nothing is dropped quietly. A row the
analyst wrote is either a report to read or a problem to report back, and
never neither, because a row that vanishes is a report they believe was
processed and was not.
"""

import pytest
from openpyxl import Workbook

from vigiflow_tasks.links import LinksError, read_links

GUID_A = "e71a7f06-ba16-415e-a827-134939a6323e"
GUID_B = "6142776a-503d-45c3-8649-89f0c0d0a6c0"
URL = "https://vigiflow.who-umc.org/dataentry/{}"


def _write(tmp_path, rows, header="Links"):
    book = Workbook()
    sheet = book.active
    if header is not None:
        sheet.append([header])
    for row in rows:
        sheet.append([row])
    path = tmp_path / "Links.xlsx"
    book.save(path)
    return path


def test_reads_the_links_and_their_report_ids(tmp_path):
    path = _write(tmp_path, [URL.format(GUID_A), URL.format(GUID_B)])
    listed = read_links(path)
    assert [r.guid for r in listed.reports] == [GUID_A, GUID_B]
    assert listed.reports[0].url.endswith(GUID_A)
    assert listed.problems == []


def test_a_file_with_no_header_still_works(tmp_path):
    path = _write(tmp_path, [URL.format(GUID_A)], header=None)
    assert [r.guid for r in read_links(path).reports] == [GUID_A]


@pytest.mark.parametrize("header", ["Links", "link", "URL", "Enlace"])
def test_the_link_column_is_found_by_any_usual_name(tmp_path, header):
    path = _write(tmp_path, [URL.format(GUID_A)], header=header)
    assert len(read_links(path).reports) == 1


def test_a_bare_guid_without_the_url_is_accepted(tmp_path):
    """An analyst pasting from the id column produces exactly this."""
    listed = read_links(_write(tmp_path, [GUID_A]))
    assert listed.reports[0].guid == GUID_A
    assert listed.reports[0].url == URL.format(GUID_A)


# -- rows that cannot be used ----------------------------------------------


def test_a_row_that_is_not_a_link_becomes_a_problem_not_a_silent_skip(tmp_path):
    """The analyst has to be told, so the row survives as a transaction."""
    path = _write(tmp_path, [URL.format(GUID_A), "N/A", "", URL.format(GUID_B)])
    listed = read_links(path)

    assert len(listed.reports) == 2
    assert [p.row for p in listed.problems] == [3]
    assert listed.problems[0].value == "N/A"
    assert listed.rows == 3  # two links and one problem; the blank is nothing


def test_a_link_to_another_system_is_refused_even_with_a_real_guid(tmp_path):
    """The robot does not browse to an arbitrary address that arrived by email."""
    path = _write(tmp_path, [f"https://example.org/dataentry/{GUID_A}"])
    listed = read_links(path)
    assert listed.reports == []
    assert len(listed.problems) == 1


def test_a_vigiflow_address_with_the_wrong_path_is_still_opened(tmp_path):
    """That is the case where a screenshot tells the analyst something."""
    path = _write(tmp_path, ["https://vigiflow.who-umc.org/searchicsrs"])
    listed = read_links(path)
    assert len(listed.reports) == 1
    assert listed.reports[0].guid == ""


def test_a_file_of_nothing_usable_still_reports_every_row(tmp_path):
    """Previously this raised, which told the analyst nothing about which rows."""
    listed = read_links(_write(tmp_path, ["nope", "also nope"]))
    assert listed.reports == []
    assert [p.row for p in listed.problems] == [2, 3]


# -- duplicates are not problems -------------------------------------------


def test_the_same_report_listed_twice_is_processed_once(tmp_path):
    """A duplicate would otherwise take two rows and two correlatives."""
    path = _write(tmp_path, [URL.format(GUID_A), URL.format(GUID_A), URL.format(GUID_B)])
    listed = read_links(path)
    assert [r.guid for r in listed.reports] == [GUID_A, GUID_B]
    assert any("duplicate" in s for s in listed.skipped)
    assert listed.problems == []


# -- the file itself -------------------------------------------------------


def test_a_missing_file_says_so(tmp_path):
    with pytest.raises(LinksError, match="not found"):
        read_links(tmp_path / "absent.xlsx")


def test_a_file_with_no_rows_at_all_says_so(tmp_path):
    with pytest.raises(LinksError, match="no rows"):
        read_links(_write(tmp_path, ["", ""]))
