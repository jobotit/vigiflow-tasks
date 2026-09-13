"""Access to VigiFlow."""

from vigiflow_tasks.vigiflow.base import VigiFlowClient, VigiFlowError
from vigiflow_tasks.vigiflow.factory import open_client

__all__ = ["VigiFlowClient", "VigiFlowError", "open_client"]
