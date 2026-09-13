"""The shape of the data that crosses the work item queue.

Kept free of any VigiFlow or Excel specifics so both sides of the queue can be
unit tested without a browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReportRecord:
    """One health report as read from VigiFlow.

    ``fields`` holds raw field name to value pairs. The Excel writer turns
    those into cells using ``resources/field_mapping.json``, so adding a field
    to the extraction does not require a code change here.
    """

    report_id: str
    fields: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {"report_id": self.report_id, "fields": self.fields}
