"""Numbering for column EV.

EV counts the analyses the analyst performs, which runs opposite to the
obvious reading. A report the notifying clinic already assessed reads S/E,
because the analyst has nothing to analyse. One the clinic left empty takes
the next number, because the analyst does the work.

Getting this backwards would fill the column with plausible but wrong values
that nobody would spot, so it is tested on its own.
"""

from vigiflow_tasks.causality import NOT_ASSESSED, assign_ev_numbers


class Rec:
    def __init__(self, report_id):
        self.report_id = report_id


def test_a_report_the_clinic_assessed_reads_s_e():
    """No number is spent on it, because the analyst does nothing."""
    records = [Rec("a"), Rec("b"), Rec("c"), Rec("d")]
    numbers = assign_ev_numbers(records, clinic_assessed_ids={"a", "c"})
    assert numbers == {"a": NOT_ASSESSED, "b": 1, "c": NOT_ASSESSED, "d": 2}


def test_the_correlative_skips_rather_than_numbering_the_s_e_rows():
    """Unlike column D, which numbers every row, EV counts only the analyses.

    A gap here would misstate how much work was done.
    """
    records = [Rec(str(n)) for n in range(6)]
    numbers = assign_ev_numbers(records, clinic_assessed_ids={"1", "4", "5"})
    assert [v for v in numbers.values() if v != NOT_ASSESSED] == [1, 2, 3]


def test_nothing_assessed_by_the_clinic_numbers_every_row():
    records = [Rec("a"), Rec("b")]
    assert assign_ev_numbers(records, clinic_assessed_ids=set()) == {"a": 1, "b": 2}


def test_everything_assessed_by_the_clinic_gives_every_row_s_e():
    records = [Rec("a"), Rec("b"), Rec("c")]
    numbers = assign_ev_numbers(records, clinic_assessed_ids={"a", "b", "c"})
    assert set(numbers.values()) == {NOT_ASSESSED}


def test_the_correlative_can_start_anywhere():
    records = [Rec("a"), Rec("b")]
    numbers = assign_ev_numbers(records, clinic_assessed_ids=set(), start=177)
    assert numbers == {"a": 177, "b": 178}


def test_plain_dicts_work_as_well_as_records():
    """Batches carry their reports as dicts once they have been through the queue."""
    records = [{"report_id": "a"}, {"report_id": "b"}]
    assert assign_ev_numbers(records, clinic_assessed_ids={"b"}) == {"a": 1, "b": NOT_ASSESSED}


def test_a_report_that_could_not_be_opened_gets_no_ev_number():
    """Not the same as "the clinic did not assess it".

    An unread report has no verified answer. Treating it as unassessed hands
    it an EV number, which claims the analyst did work nobody checked.
    """
    from vigiflow_tasks.causality import CLINIC_ASSESSED_FIELD, assign_ev_column
    from vigiflow_tasks.models import ReportRecord

    def record(report_id, assessed):
        return ReportRecord(report_id=report_id, fields={CLINIC_ASSESSED_FIELD: assessed})

    records = [
        record("a", False),  # the analyst analyses it
        record("b", True),   # the clinic already did
        record("c", None),   # could not be read
        record("d", False),
    ]
    assert assign_ev_column(records) == {
        "a": 1,
        "b": NOT_ASSESSED,
        "c": None,
        "d": 3,  # c consumed 2, so d keeps the number it would have had
    }
