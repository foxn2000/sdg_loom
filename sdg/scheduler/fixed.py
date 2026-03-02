"""sdg/scheduler/fixed.py - 固定並行数スケジューラー

既存の pipeline_streaming.py の並行処理ロジックを Strategy パターンとして抽出。
asyncio.Semaphore で並行数を制限しながら全タスクを処理する。
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, Set

from ..executors.core import StreamingResult
from .base import SchedulerConfig


class FixedScheduler:
    """
    固定並行数スケジューラー。

    asyncio.Semaphore で並行数を制限しながら全タスクを処理する。
    既存 pipeline_streaming.py の動作を完全に再現。
    """

    def __init__(self, config: SchedulerConfig) -> None:
        self._max_concurrent = config.max_concurrent
        self._enable_scheduling = config.enable_scheduling
        self._max_pending_tasks = config.max_pending_tasks
        self._chunk_size = config.chunk_size
        self._enable_memory_optimization = config.enable_memory_optimization
        self._max_cache_size = config.max_cache_size
        self._enable_memory_monitoring = config.enable_memory_monitoring
        self._gc_interval = config.gc_interval
        self._memory_threshold_mb = config.memory_threshold_mb

    async def schedule(
        self,
        dataset: Iterable,
        task_factory: Callable[[int, dict], Awaitable[StreamingResult]],
        skip_indices: Set[int],
    ) -> AsyncIterator[StreamingResult]:
        """
        データセットに対してタスクをスケジュールし、結果を順次 yield。
        Semaphore で並行数を制御する。

        Args:
            dataset: 処理対象イテラブル（各要素が行データ dict）
            task_factory: (row_index, row_data) -> StreamingResult の非同期ファクトリ
            skip_indices: スキップする行インデックスの集合（resume 用）
        """
        from ..executors.scheduling import (
            HierarchicalTaskScheduler,
            SchedulingMemoryConfig,
            SchedulerConfig as _HierSchedulerConfig,
            StreamingContextManager,
        )

        semaphore = asyncio.Semaphore(self._max_concurrent)
        result_queue: asyncio.Queue[StreamingResult] = asyncio.Queue()
        completed = 0
        total_started = 0

        # Phase 2 オプション機能の初期化
        scheduler_config = _HierSchedulerConfig(
            max_pending_tasks=self._max_pending_tasks,
            chunk_size=self._chunk_size,
            enable_scheduling=self._enable_scheduling,
        )
        scheduler = HierarchicalTaskScheduler(config=scheduler_config)
        memory_config = SchedulingMemoryConfig(
            max_cache_size=self._max_cache_size,
            enable_memory_optimization=self._enable_memory_optimization,
            enable_monitoring=self._enable_memory_monitoring,
            gc_interval=self._gc_interval,
            memory_threshold_mb=self._memory_threshold_mb,
        )
        ctx_manager = StreamingContextManager(config=memory_config)

        async def process_row(row_index: int, row_data: dict) -> None:
            async with semaphore:
                try:
                    result = await task_factory(row_index, row_data)
                    await result_queue.put(result)
                except Exception as e:
                    await result_queue.put(
                        StreamingResult(row_index=row_index, data={}, error=e)
                    )
                finally:
                    if scheduler.is_enabled:
                        await scheduler.mark_task_completed()
                    if ctx_manager.is_enabled:
                        await ctx_manager.mark_completed(row_index)

        try:
            tasks = []

            if self._enable_scheduling:
                # 階層的スケジューラ経由でタスク起動
                async for item in scheduler.schedule(dataset):
                    if item.index in skip_indices:
                        continue
                    task = asyncio.create_task(process_row(item.index, item.data))
                    tasks.append(task)
                    total_started += 1
            else:
                # 直接タスク生成（標準パス）
                for i, row in enumerate(dataset):
                    if i in skip_indices:
                        continue
                    task = asyncio.create_task(process_row(i, row))
                    tasks.append(task)
                    total_started += 1

            while completed < total_started:
                result = await result_queue.get()
                completed += 1
                yield result

            await asyncio.gather(*tasks)

        finally:
            if ctx_manager.is_enabled:
                await ctx_manager.release_all()


__all__ = ["FixedScheduler"]
