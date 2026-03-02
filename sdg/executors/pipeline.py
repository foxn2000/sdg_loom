from __future__ import annotations

from .pipeline_core import process_single_row
from .pipeline_legacy import run_pipeline

__all__ = [
    "process_single_row",
    "run_pipeline",
]
