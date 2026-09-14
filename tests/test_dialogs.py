"""VigiFlow's notice dialog, tested without a browser.

On 14-09-2026 a maintenance notice covered every report page. Its backdrop
swallowed the clicks that open the notifier, patient and evaluation sections,
and four columns came back empty on every row with no warning anywhere. These
tests pin down the fix: close that notice and nothing else, only when it is the
dialog on top, and say so when a section still cannot be opened.
"""

from vigiflow_tasks.vigiflow import dialogs
from vigiflow_tasks.vigiflow import locators as loc

NOTICE_TITLE = "Avisos / Información relevante"
NOT_FOUND_TITLE = "El reporte no pudo ser encontrado"


class FakeLocator:
    """Enough of a Playwright locator for a stack of dialogs.

    ``scope`` is the kind of dialog this locator is inside, or None for the
    whole page. Dialogs are "notice" or "other".
    """

    def __init__(self, page, selector, scope=None):
        self.page = page
        self.selector = selector
        self.scope = scope

    # -- narrowing ---------------------------------------------------------

    @property
    def first(self):
        return self._pick(0)

    @property
    def last(self):
        return self._pick(-1)

    def _pick(self, index):
        if self.selector == loc.DIALOG:
            stack = self.page.stack()
            return FakeLocator(self.page, "dialog", scope=stack[index] if stack else "none")
        return self

    def locator(self, selector):
        return FakeLocator(self.page, selector, scope=self.scope)

    # -- reading -----------------------------------------------------------

    def count(self):
        stack = self.page.stack()
        if self.selector == loc.DIALOG:
            return len(stack)
        if self.selector == "dialog":
            return 0 if self.scope == "none" else 1
        if self.selector == loc.NOTICE_CLOSE:
            if self.scope is None:
                return 1 if "notice" in stack else 0
            return 1 if self.scope == "notice" else 0
        if self.selector == loc.DIALOG_TITLE:
            return 0 if self.scope in (None, "none") else 1
        return 0

    def is_visible(self):
        return self.count() > 0

    def get_attribute(self, name):
        return "notifyUsersClose" if name == "id" and self.selector == loc.NOTICE_CLOSE else None

    def inner_text(self):
        if self.selector == loc.NOTICE_CLOSE:
            return "Ok"
        if self.selector == loc.DIALOG_TITLE:
            return NOTICE_TITLE if self.scope == "notice" else self.page.other
        return ""

    # -- acting ------------------------------------------------------------

    def click(self, **_):
        self.page.clicks.append(self.selector)
        # A click only lands if this notice is the dialog on top.
        if self.selector == loc.NOTICE_CLOSE and self.page.stack()[-1:] == ["notice"]:
            self.page.notices -= 1
        else:
            raise TimeoutError("another element would receive the click")


class FakePage:
    """Queued notices, and optionally another dialog on top of them."""

    def __init__(self, notices=0, other=None):
        self.notices = notices
        self.other = other
        self.clicks = []

    def stack(self):
        """Visible dialogs, bottom first. Queued notices show one at a time."""
        stack = ["notice"] if self.notices > 0 else []
        if self.other:
            stack.append("other")
        return stack

    def locator(self, selector):
        return FakeLocator(self, selector)

    def wait_for_timeout(self, _):
        pass

    def wait_for_selector(self, selector, **_):
        if FakeLocator(self, selector).count() == 0:
            raise TimeoutError(selector)


def test_the_notice_is_closed():
    page = FakePage(notices=1)
    assert dialogs.dismiss_notices(page) == 1
    assert page.clicks == [loc.NOTICE_CLOSE]
    assert dialogs.blocking_dialog(page) is None


def test_queued_notices_are_all_closed():
    assert dialogs.dismiss_notices(FakePage(notices=3)) == 3


def test_a_notice_that_keeps_reopening_does_not_loop_forever():
    assert dialogs.dismiss_notices(FakePage(notices=100)) == dialogs.MAX_NOTICES


def test_nothing_is_clicked_when_there_is_no_notice():
    page = FakePage()
    assert dialogs.dismiss_notices(page) == 0
    assert dialogs.dismiss_notices(page, wait_ms=10) == 0
    assert page.clicks == []
    assert dialogs.blocking_dialog(page) is None


def test_any_other_dialog_is_left_alone_and_named():
    """"El reporte no pudo ser encontrado" is the evidence for a broken link."""
    page = FakePage(other=NOT_FOUND_TITLE)
    assert dialogs.dismiss_notices(page) == 0
    assert page.clicks == []
    assert dialogs.blocking_dialog(page) == NOT_FOUND_TITLE


def test_a_notice_underneath_another_dialog_is_not_clicked():
    """Seen live: "not found" opened on top of the notice.

    Clicking the notice's button then waits out its timeout on the upper
    dialog's backdrop, so nothing is clicked, and the dialog reported is the
    one on top, which is the one a person would see.
    """
    page = FakePage(notices=1, other=NOT_FOUND_TITLE)
    assert dialogs.dismiss_notices(page) == 0
    assert page.clicks == []
    assert dialogs.blocking_dialog(page) == NOT_FOUND_TITLE


def test_a_report_id_in_a_dialog_title_is_masked():
    page = FakePage(other="¿Guardar los cambios de PE-DIGEMID-300289386?")
    assert dialogs.blocking_dialog(page) == "¿Guardar los cambios de <report>?"


def test_the_reply_names_incomplete_rows_and_the_dialog():
    from tasks import _incomplete_note

    rows = [
        {"unopened": ["Paciente"], "blocked_by": NOTICE_TITLE},
        {"unopened": ["Evaluación"], "blocked_by": None},
    ]
    note = _incomplete_note(rows)
    assert note.startswith("2 filas están incompletas")
    assert "GRAVEDAD" in note
    assert NOTICE_TITLE in note


def test_a_single_incomplete_row_reads_as_singular():
    from tasks import _incomplete_note

    assert _incomplete_note([{"unopened": ["Paciente"]}]).startswith("1 fila está incompleta")
