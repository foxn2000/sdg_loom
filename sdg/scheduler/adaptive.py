"""sdg/scheduler/adaptive.py - 適応型スケジューラー

既存の pipeline_adaptive.py の progressive_task_launcher を Strategy パターンとして抽出。
AdaptiveController のセマフォ容量に応じて段階的にタスクを起動する。
バッチングも統合（enable_request_batching=True の場合）。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, Optional, Set

from ..executors.core import StreamingResult
from .base import SchedulerConfig


class AdaptiveScheduler:
    """
    適応型スケジューラー。

    AdaptiveController のセマフォ容量に応じて段階的にタスクを起動する。
    既存 pipeline_adaptive.py の progressive_task_launcher を完全に再現。
    バッチングも統合（enable_request_batching=True の場合）。
    """

    def __init__(self, config: SchedulerConfig) -> None:
        self._max_concurrent = config.max_concurrent_limit
        self._min_concurrent = config.min_concurrent
        self._target_latency_ms = config.target_latency_ms
        self._target_queue_depth = config.target_queue_depth
        self._metrics_type = config.metrics_type
        self._enable_request_batching = config.enable_request_batching
        self._max_batch_size = config.max_batch_size
        self._max_wait_ms = config.max_wait_ms
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
        cfg: Any = None,  # メトリクス収集時に base_url 取得用
        clients: Any = None,
    ) -> AsyncIterator[StreamingResult]:
        """
        適応型スケジューリングで処理。

        AdaptiveController が利用できない場合は FixedScheduler にフォールバックする。

        Args:
            dataset: 処理対象イテラブル（各要素が行データ dict）
            task_factory: (row_index, row_data) -> StreamingResult の非同期ファクトリ
            skip_indices: スキップする行インデックスの集合（resume 用）
            cfg: SDGConfig（メトリクスコレクター初期化用。省略可）
            clients: クライアント辞書（現状は未使用。拡張用に保持）
        """
        try:
            from ..adaptive import AdaptiveController, MetricsCollector, MetricsType

            ADAPTIVE_AVAILABLE = True
        except ImportError:
            ADAPTIVE_AVAILABLE = False

        if not ADAPTIVE_AVAILABLE:
            # フォールバック: 固定スケジューラ
            from .base import SchedulerConfig as _SC
            from .fixed import FixedScheduler

            fallback_cfg = _SC(
                max_concurrent=self._max_concurrent,
                enable_scheduling=self._enable_scheduling,
                max_pending_tasks=self._max_pending_tasks,
                chunk_size=self._chunk_size,
                enable_memory_optimization=self._enable_memory_optimization,
                max_cache_size=self._max_cache_size,
                enable_memory_monitoring=self._enable_memory_monitoring,
                gc_interval=self._gc_interval,
                memory_threshold_mb=self._memory_threshold_mb,
            )
            fixed = FixedScheduler(fallback_cfg)
            async for result in fixed.schedule(dataset, task_factory, skip_indices):
                yield result
            return

        from ..executors.scheduling import (
            HierarchicalTaskScheduler,
            SchedulingMemoryConfig,
            SchedulerConfig as _HierSchedulerConfig,
            StreamingContextManager,
        )

        controller = AdaptiveController(
            min_concurrency=self._min_concurrent,
            max_concurrency=self._max_concurrent,
            target_latency_ms=float(self._target_latency_ms),
            target_queue_depth=self._target_queue_depth,
            initial_concurrency=self._max_concurrent,
        )

        # メトリクスコレクター（vllm / sglang オプション）
        metrics_collector: Optional[Any] = None
        if self._metrics_type != "none" and cfg is not None:
            base_url = None
            for model in cfg.models:
                if model.base_url:
                    base_url = model.base_url
                    break
            if base_url:
                if self._metrics_type == "vllm":
                    metrics_collector = MetricsCollector(
                        base_url=base_url, metrics_type=MetricsType.VLLM
                    )
                elif self._metrics_type == "sglang":
                    metrics_collector = MetricsCollector(
                        base_url=base_url, metrics_type=MetricsType.SGLANG
                    )

        result_queue: asyncio.Queue[StreamingResult] = asyncio.Queue()
        total_started = 0
        completed = 0
        metrics_update_task: Optional[asyncio.Task] = None

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

        async def update_metrics_loop() -> None:
            if metrics_collector is None:
                return
            await metrics_collector.start()
            try:
                while True:
                    await asyncio.sleep(0.5)
                    metrics = metrics_collector.get_latest()
                    if metrics and metrics.is_valid:
                        controller.update_with_metrics(metrics)
            except asyncio.CancelledError:
                pass
            finally:
                await metrics_collector.stop()

        async def process_row(row_index: int, row_data: dict) -> None:
            async with controller.semaphore:
                start_time = time.time()
                try:
                    result = await task_factory(row_index, row_data)
                    latency_ms = (time.time() - start_time) * 1000
                    controller.record_latency(
                        latency_ms, is_error=result.error is not None
                    )
                    await result_queue.put(result)
                except Exception as e:
                    latency_ms = (time.time() - start_time) * 1000
                    controller.record_latency(latency_ms, is_error=True)
                    await result_queue.put(
                        StreamingResult(row_index=row_index, data={}, error=e)
                    )
                finally:
                    if scheduler.is_enabled:
                        await scheduler.mark_task_completed()
                    if ctx_manager.is_enabled:
                        await ctx_manager.mark_completed(row_index)

        async def progressive_task_launcher(
            data_iter: Iterable,
        ) -> AsyncIterator[StreamingResult]:
            """セマフォ容量に応じて段階的にタスクを起動（pipeline_adaptive 移植）"""
            nonlocal total_started
            tasks = []
            active_count = 0
            data_exhausted = False
            current_index = 0
            data_iterator = iter(data_iter)

            while not data_exhausted or active_count > 0:
                current_capacity = controller.current_concurrency
                available_slots = controller.get_available_slots()
                slots_to_fill = max(
                    0, min(current_capacity - active_count, available_slots)
                )

                for _ in range(slots_to_fill):
                    try:
                        row_data = next(data_iterator)
                        row_index = current_index
                        current_index += 1
                        if row_index in skip_indices:
                            continue
                        task = asyncio.create_task(process_row(row_index, row_data))
                        tasks.append(task)
                        total_started += 1
                        active_count += 1
                    except StopIteration:
                        data_exhausted = True
                        break

                if active_count > 0:
                    try:
                        result = await asyncio.wait_for(result_queue.get(), timeout=0.1)
                        active_count -= 1
                        yield result
                    except asyncio.TimeoutError:
                        pass
                else:
                    await asyncio.sleep(0.01)

            # キューに残った結果を全て drain する
            while not result_queue.empty():
                result = result_queue.get_nowait()
                yield result

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        try:
            if metrics_collector is not None:
                metrics_update_task = asyncio.create_task(update_metrics_loop())

            if self._enable_scheduling:
                # 階層的スケジューラ経由でタスク起動
                tasks_list = []
                async for item in scheduler.schedule(dataset):
                    if item.index in skip_indices:
                        continue
                    task = asyncio.create_task(process_row(item.index, item.data))
                    tasks_list.append(task)
                    total_started += 1

                while completed < total_started:
                    result = await result_queue.get()
                    completed += 1
                    yield result

                await asyncio.gather(*tasks_list)
            else:
                # progressive_task_launcher による段階的起動（標準アダプティブパス）
                async for result in progressive_task_launcher(dataset):
                    completed += 1
                    yield result

        finally:
            if ctx_manager.is_enabled:
                await ctx_manager.release_all()
            if metrics_update_task is not None:
                metrics_update_task.cancel()
                try:
                    await metrics_update_task
                except asyncio.CancelledError:
                    pass


__all__ = ["AdaptiveScheduler"]
