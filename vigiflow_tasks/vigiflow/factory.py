"""Opens a VigiFlow session for the current run."""

from __future__ import annotations

import logging

from vigiflow_tasks.config import VigiFlowConfig, client_kind
from vigiflow_tasks.vigiflow.base import VigiFlowClient, VigiFlowError

LOGGER = logging.getLogger(__name__)


def open_client(kind: str | None = None) -> VigiFlowClient:
    """Build a client without entering it, so the caller controls the ``with``.

    Credentials are read from the vault here rather than at import time, so
    nothing touches the vault until a real session is actually opened.
    """
    kind = (kind or client_kind()).lower()

    if kind == "browser":
        from vigiflow_tasks.vigiflow.browser_client import BrowserVigiFlowClient

        return BrowserVigiFlowClient(VigiFlowConfig.from_vault())

    raise VigiFlowError(f"Unknown VIGIFLOW_CLIENT {kind!r}. Only 'browser' is supported.")
