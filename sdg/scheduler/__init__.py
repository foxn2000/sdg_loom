"""sdg/scheduler - スケジューラー戦略パッケージ

Strategy パターンで実装されたスケジューラーを提供する。
PipelineEngine が RunConfig に基づいて適切なスケジューラーを選択する。
"""

from .adaptive import AdaptiveScheduler
from .base import RowTask, SchedulerConfig
from .fixed import FixedScheduler

__all__ = [
    "RowTask",
    "SchedulerConfig",
    "FixedScheduler",
    "AdaptiveScheduler",
]
