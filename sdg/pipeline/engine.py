"""sdg/pipeline/engine.py - 統合パイプラインエンジン

既存の 3 Runner × 3 Pipeline = 9 パスの重複コードを
1 つの実行エンジンに集約する。

スケジューリング戦略は RunConfig.concurrency.adaptive フラグで選択され、
FixedScheduler または AdaptiveScheduler に委譲される。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Iterable, Optional, Set

from ..config import PyBlock
from ..executors.ai import _build_clients
from ..executors.core import ExecutionContext, StreamingResult
from ..executors.pipeline_core import process_single_row
from ..executors.python import _load_python_function
from ..io import (
    AsyncBufferedWriter,
    apply_mapping,
    count_lines_fast,
    load_processed_indices,
    read_csv,
    read_hf_dataset,
    read_jsonl,
)
from ..logger import get_logger
from ..profiler import ProfileCollector
from ..scheduler.adaptive import AdaptiveScheduler
from ..scheduler.base import SchedulerConfig
from ..scheduler.fixed import FixedScheduler
from .result import RunReport
from .run_config import RunConfig


class PipelineEngine:
    """
    統合パイプラインエンジン。

    既存の 3 Runner × 3 Pipeline = 9 パスの重複を解消する
    単一の実行エンジン。スケジューリング戦略は RunConfig で選択される。

    全ての write loop 共通処理をここに集約:
    - AsyncBufferedWriter による I/O
    - プログレス表示
    - エラーハンドリング
    - プロファイラー連携
    - resume 機能
    """

    def __init__(self, cfg: Any, run_config: Optional[RunConfig] = None):
        """
        Args:
            cfg: SDGConfig インスタンス（load_config() の戻り値）
            run_config: 実行パラメータ。省略時はデフォルト RunConfig を使用
        """
        self._cfg = cfg
        self._run_config = run_config or RunConfig()

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _build_task_factory(
        self,
        clients: dict,
        python_functions: dict,
    ) -> Any:
        """行処理タスクファクトリを構築して返す"""
        cfg = self._cfg
        rc = self._run_config

        async def task_factory(row_index: int, row_data: dict) -> StreamingResult:
            row_exec_ctx = ExecutionContext(cfg)
            try:
                result_data = await process_single_row(
                    row_index=row_index,
                    initial_context=row_data,
                    cfg=cfg,
                    clients=clients,
                    exec_ctx=row_exec_ctx,
                    save_intermediate=rc.save_intermediate,
                    python_functions=python_functions,
                )
                return StreamingResult(
                    row_index=row_index, data=result_data, error=None
                )
            except Exception as e:
                return StreamingResult(row_index=row_index, data={}, error=e)

        return task_factory

    def _create_scheduler(self) -> Any:
        """RunConfig から SchedulerConfig を生成し、適切なスケジューラーを返す。"""
        cc = self._run_config.concurrency
        mm = self._run_config.memory

        cfg = SchedulerConfig(
            max_concurrent=cc.max_concurrent,
            min_concurrent=cc.min_concurrent,
            adaptive=cc.adaptive,
            max_concurrent_limit=cc.max_concurrent_limit,
            target_latency_ms=cc.target_latency_ms,
            target_queue_depth=cc.target_queue_depth,
            metrics_type=cc.metrics_type,
            enable_request_batching=cc.enable_request_batching,
            max_batch_size=cc.max_batch_size,
            max_wait_ms=cc.max_wait_ms,
            enable_scheduling=mm.enable_scheduling,
            max_pending_tasks=mm.max_pending_tasks,
            chunk_size=mm.chunk_size,
            enable_memory_optimization=mm.enable_memory_optimization,
            max_cache_size=mm.max_cache_size,
            enable_memory_monitoring=mm.enable_memory_monitoring,
            gc_interval=mm.gc_interval,
            memory_threshold_mb=mm.memory_threshold_mb,
        )

        if cc.adaptive:
            return AdaptiveScheduler(cfg)
        else:
            return FixedScheduler(cfg)

    def _apply_transport_config(self) -> None:
        """cfg.optimization に TransportConfig の設定を反映する。"""
        tr_cfg = self._run_config.transport
        self._cfg.optimization = {
            "use_shared_transport": tr_cfg.use_shared_transport,
            "http2": tr_cfg.http2,
            "retry_on_empty": tr_cfg.retry_on_empty,
        }

    def _setup_resume(self, output_path: str) -> tuple[Set[int], bool]:
        """
        Resume モードの設定を行い、スキップ済みインデックスと追記フラグを返す。

        Returns:
            (processed_indices, append_mode)
        """
        rc = self._run_config
        logger = get_logger()
        processed_indices: Set[int] = set()
        append_mode = False

        if rc.resume.resume and os.path.exists(output_path):
            processed_indices, processed_count = load_processed_indices(output_path)
            if processed_count > 0:
                append_mode = True
                if rc.show_progress:
                    logger.info(f"Resuming from {processed_count} processed records.")

        actual_skip = rc.resume.skip_lines if not rc.resume.resume else 0
        if actual_skip > 0 and rc.show_progress:
            logger.info(f"Skipping first {actual_skip} lines.")

        return processed_indices, append_mode

    def _load_dataset(self) -> tuple[Iterable, Optional[int]]:
        """
        データセットを読み込み、イテラブルと総行数を返す。

        Returns:
            (dataset, total_count)  total_count は不明な場合 None
        """
        rc = self._run_config
        ds_cfg = rc.data_source
        actual_skip = rc.resume.skip_lines if not rc.resume.resume else 0
        total: Optional[int] = None

        if ds_cfg.input_path:
            ds_input = ds_cfg.input_path
            if ds_input.endswith(".jsonl"):
                total = count_lines_fast(ds_input)
                if total is not None and actual_skip > 0:
                    total = max(0, total - actual_skip)
                if rc.resume.max_inputs is not None and total is not None:
                    total = min(total, rc.resume.max_inputs)
                ds = read_jsonl(
                    ds_input,
                    max_inputs=rc.resume.max_inputs,
                    skip_lines=actual_skip,
                )
            elif ds_input.endswith(".csv"):
                line_count = count_lines_fast(ds_input)
                if line_count is not None:
                    total = line_count - 1  # ヘッダー行を除く
                    if actual_skip > 0:
                        total = max(0, total - actual_skip)
                    if rc.resume.max_inputs is not None:
                        total = min(total, rc.resume.max_inputs)
                ds = read_csv(
                    ds_input,
                    max_inputs=rc.resume.max_inputs,
                    skip_lines=actual_skip,
                )
            else:
                raise ValueError("Unsupported input format. Use .jsonl or .csv")
        elif ds_cfg.dataset_name:
            ds = read_hf_dataset(
                ds_cfg.dataset_name,
                ds_cfg.subset,
                ds_cfg.split,
                max_inputs=rc.resume.max_inputs,
                skip_lines=actual_skip,
            )
            total = rc.resume.max_inputs
            if total is not None and actual_skip > 0:
                total = max(0, total - actual_skip)
        else:
            raise ValueError("Either input_path or dataset_name must be provided")

        if ds_cfg.mapping:
            ds = apply_mapping(ds, ds_cfg.mapping)

        return ds, total

    def _log_run_config(
        self,
        total_count: Optional[int],
        remaining: Optional[int],
    ) -> None:
        """実行開始時のヘッダーと設定テーブルをログ表示する。"""
        rc = self._run_config
        if not rc.show_progress:
            return

        logger = get_logger()
        mode = "Adaptive" if rc.concurrency.adaptive else "Streaming"
        logger.header(f"SDG Pipeline - {mode} Mode", f"{mode} pipeline execution")

        total_str = str(total_count) if total_count is not None else "unknown"
        remaining_str = str(remaining) if remaining is not None else "unknown"

        # resume による処理済み件数を逆算
        processed_count = 0
        if total_count is not None and remaining is not None:
            processed_count = total_count - remaining

        cc = rc.concurrency
        config_info: dict = {
            "Input Data Count": total_str,
            "Already Processed": processed_count,
            "Remaining": remaining_str,
        }
        if cc.adaptive:
            config_info.update(
                {
                    "Max Concurrency": cc.max_concurrent_limit,
                    "Min Concurrency": cc.min_concurrent,
                    "Target Latency": f"{cc.target_latency_ms}ms",
                    "Metrics Type": cc.metrics_type,
                }
            )
        else:
            config_info["Concurrency"] = cc.max_concurrent

        logger.table("Execution Configuration", config_info)

    def _init_profiler(self) -> Optional[ProfileCollector]:
        """ProfileCollector を初期化して返す。無効な場合は None。"""
        prof_cfg = self._run_config.profile
        if not prof_cfg.enable:
            return None
        profiler = ProfileCollector(output_fields=prof_cfg.output_fields)
        profiler.start()
        return profiler

    def _finalize_profiler(
        self,
        profiler: Optional[ProfileCollector],
        output_path: str,
    ) -> None:
        """プロファイル結果を terminal 表示・JSON 出力する。"""
        if profiler is None:
            return

        rc = self._run_config
        logger = get_logger()
        profiler.stop()
        profile_data = profiler.get_profile()

        if rc.show_progress:
            logger.print_profile(profile_data)

        prof_cfg = rc.profile
        if prof_cfg.output_path:
            with open(prof_cfg.output_path, "w", encoding="utf-8") as f:
                json.dump(profile_data, f, ensure_ascii=False, indent=2)
            if rc.show_progress:
                logger.info(f"Profile saved to: {prof_cfg.output_path}")

    def _build_report(
        self,
        total: Optional[int],
        completed: int,
        errors: int,
        elapsed_ms: float,
    ) -> RunReport:
        """RunReport を生成して返す。"""
        return RunReport(
            total_rows=total or completed,
            completed_rows=completed,
            error_rows=errors,
            elapsed_ms=elapsed_ms,
        )

    # ------------------------------------------------------------------
    # 非同期実行コア（統合 write loop）
    # ------------------------------------------------------------------

    async def _run_async(
        self,
        dataset: Iterable,
        output_path: str,
        processed_indices: Set[int],
        append_mode: bool,
        total_count: Optional[int],
        profiler: Optional[ProfileCollector],
    ) -> tuple[int, int]:
        """
        統合 write loop - 全 3 runners の重複を解消。

        Returns:
            (completed, errors) のタプル
        """
        completed = 0
        errors = 0
        rc = self._run_config
        io = rc.io

        logger = get_logger()
        progress = logger.create_progress() if rc.show_progress else None

        # クライアントと Python 関数をプリロード
        clients = _build_clients(self._cfg)
        python_functions: dict = {}
        for block in self._cfg.blocks:
            if isinstance(block, PyBlock):
                fn_key = f"{block.exec}_{block.function or block.entrypoint}"
                python_functions[fn_key] = _load_python_function(block)

        task_factory = self._build_task_factory(clients, python_functions)
        scheduler = self._create_scheduler()

        mode_label = "adaptive" if rc.concurrency.adaptive else "streaming"

        async with AsyncBufferedWriter(
            output_path,
            buffer_size=io.buffer_size,
            flush_interval=io.flush_interval,
            append=append_mode,
        ) as writer:

            # task_ref はプログレスコンテキスト内外で共有するリラプター
            task_ref: list[Any] = [None]

            async def _process_all() -> None:
                nonlocal completed, errors

                async for result in scheduler.schedule(
                    dataset, task_factory, processed_indices
                ):
                    completed += 1
                    if result.error:
                        errors += 1
                        logger.debug(f"Error in row {result.row_index}: {result.error}")
                        await writer.write(
                            {
                                "_row_index": result.row_index,
                                "_error": str(result.error),
                                **result.data,
                            }
                        )
                        if profiler:
                            profiler.record_output(result.data, error=result.error)
                    else:
                        await writer.write(
                            {
                                "_row_index": result.row_index,
                                **result.data,
                            }
                        )
                        if profiler:
                            profiler.record_output(result.data)

                    if progress and task_ref[0] is not None:
                        progress.update(task_ref[0], advance=1)

            if progress:
                with progress:
                    if total_count is not None:
                        task_ref[0] = progress.add_task(
                            f"[cyan]Processing {total_count} rows ({mode_label})...",
                            total=total_count,
                        )
                    else:
                        task_ref[0] = progress.add_task(
                            f"[cyan]Processing rows ({mode_label})...",
                            total=None,
                        )
                    await _process_all()
            else:
                await _process_all()

        if rc.show_progress:
            logger.print_stats(
                {
                    "total": total_count if total_count is not None else completed,
                    "completed": completed,
                    "errors": errors,
                }
            )

        return completed, errors

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    def run(self, output_path: str) -> RunReport:
        """
        パイプラインを実行して RunReport を返す。

        Args:
            output_path: 出力ファイルパス（.jsonl または .csv）

        Returns:
            RunReport: 実行統計・結果のサマリー
        """
        self._apply_transport_config()
        processed_indices, append_mode = self._setup_resume(output_path)
        dataset, total_count = self._load_dataset()

        remaining = (
            max(0, total_count - len(processed_indices))
            if total_count is not None
            else None
        )
        self._log_run_config(total_count, remaining)
        profiler = self._init_profiler()

        start_time = time.time()
        completed, errors = asyncio.run(
            self._run_async(
                dataset,
                output_path,
                processed_indices,
                append_mode,
                remaining,
                profiler,
            )
        )
        elapsed_ms = (time.time() - start_time) * 1000

        self._finalize_profiler(profiler, output_path)
        return self._build_report(total_count, completed, errors, elapsed_ms)


__all__ = ["PipelineEngine"]
