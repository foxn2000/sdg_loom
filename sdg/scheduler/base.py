"""sdg/scheduler/base.py - スケジューラー共通データ型"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RowTask:
    """スケジュールされた行タスク（インデックス + データ）"""

    row_index: int
    data: dict[str, Any]


@dataclass
class SchedulerConfig:
    """スケジューラーの全設定を一つのオブジェクトに集約。

    PipelineEngine が RunConfig から生成して Scheduler に渡す。
    スケジューラーはこの 1 オブジェクトを受け取るだけでよい。
    """

    # ── 並行数制御 ──────────────────────────────────
    max_concurrent: int = 32
    min_concurrent: int = 1
    adaptive: bool = False  # True → AdaptiveScheduler, False → FixedScheduler
    max_concurrent_limit: int = 64  # adaptive 時の上限
    target_latency_ms: int = 3000
    target_queue_depth: int = 32
    metrics_type: str = "none"  # "none" | "vllm" | "sglang"

    # ── リクエストバッチング ────────────────────────
    enable_request_batching: bool = False
    max_batch_size: int = 32
    max_wait_ms: int = 50

    # ── 階層スケジューリング / メモリ最適化 ────────
    enable_scheduling: bool = False
    max_pending_tasks: int = 1000
    chunk_size: int = 100
    enable_memory_optimization: bool = False
    max_cache_size: int = 500
    enable_memory_monitoring: bool = False
    gc_interval: int = 100
    memory_threshold_mb: int = 1024


__all__ = ["RowTask", "SchedulerConfig"]
