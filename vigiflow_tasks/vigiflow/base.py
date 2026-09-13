"""What the tasks need from VigiFlow.

One protocol with one implementation today, which is still worth having: it
states what the consumer depends on, and it keeps the rest of the package from
importing Playwright.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class VigiFlowError(RuntimeError):
    """VigiFlow could not be used as expected. Treat as an APPLICATION error."""


@runtime_checkable
class VigiFlowClient(Protocol):
    """A signed-in VigiFlow session.

    Implementations are context managers so the browser is always closed.
    """

    def __enter__(self) -> "VigiFlowClient": ...

    def __exit__(self, exc_type, exc, tb) -> None: ...

    def login(self) -> None:
        """Authenticate. Called once per task run."""

    @property
    def page(self):
        """The signed-in page, for the scraper to read reports from."""
