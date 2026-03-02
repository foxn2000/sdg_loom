from __future__ import annotations
from typing import Any, Dict, List, Optional

from .io import (
    AsyncBufferedWriter,
    count_lines_fast,
    read_jsonl,
    read_csv,
    read_hf_dataset,
    apply_mapping,
    write_jsonl,
)
from .runners.legacy import run
from .runners.test import test_run
from .pipeline import (
    PipelineEngine,
    RunConfig,
    ConcurrencyConfig,
    IOConfig,
    ResumeConfig,
    MemoryConfig,
    ProfileConfig,
    TransportConfig,
    DataSourceConfig,
    RunReport,
    RowResult,
)


def run_streaming(
    yaml_path: str,
    input_path: Optional[str],
    output_path: str,
    max_concurrent: int = 8,
    save_intermediate: bool = False,
    show_progress: bool = True,
    use_shared_transport: bool = False,
    http2: bool = True,
    retry_on_empty: bool = True,
    enable_scheduling: bool = False,
    max_pending_tasks: int = 1000,
    chunk_size: int = 100,
    enable_memory_optimization: bool = False,
    max_cache_size: int = 500,
    enable_memory_monitoring: bool = False,
    gc_interval: int = 100,
    memory_threshold_mb: int = 1024,
    max_inputs: Optional[int] = None,
    skip_lines: int = 0,
    resume: bool = False,
    dataset_name: Optional[str] = None,
    subset: Optional[str] = None,
    split: str = "train",
    mapping: Optional[Dict[str, str]] = None,
    enable_profile: bool = False,
    profile_output_path: Optional[str] = None,
    profile_output_fields: Optional[list] = None,
):
    """固定並行数ストリーミングパイプライン実行（後方互換API）"""
    from .config import load_config

    cfg = load_config(yaml_path)
    run_config = RunConfig(
        concurrency=ConcurrencyConfig(max_concurrent=max_concurrent),
        io=IOConfig(),
        resume=ResumeConfig(
            resume=resume, skip_lines=skip_lines, max_inputs=max_inputs
        ),
        memory=MemoryConfig(
            enable_scheduling=enable_scheduling,
            max_pending_tasks=max_pending_tasks,
            chunk_size=chunk_size,
            enable_memory_optimization=enable_memory_optimization,
            max_cache_size=max_cache_size,
            enable_memory_monitoring=enable_memory_monitoring,
            gc_interval=gc_interval,
            memory_threshold_mb=memory_threshold_mb,
        ),
        profile=ProfileConfig(
            enable=enable_profile,
            output_path=profile_output_path,
            output_fields=profile_output_fields,
        ),
        transport=TransportConfig(
            use_shared_transport=use_shared_transport,
            http2=http2,
            retry_on_empty=retry_on_empty,
        ),
        data_source=DataSourceConfig(
            input_path=input_path,
            dataset_name=dataset_name,
            subset=subset,
            split=split,
            mapping=mapping,
        ),
        save_intermediate=save_intermediate,
        show_progress=show_progress,
    )
    engine = PipelineEngine(cfg, run_config)
    engine.run(output_path)


def run_streaming_adaptive(
    yaml_path: str,
    input_path: Optional[str],
    output_path: str,
    max_concurrent: int = 64,
    min_concurrent: int = 1,
    target_latency_ms: int = 3000,
    target_queue_depth: int = 32,
    metrics_type: str = "none",
    save_intermediate: bool = False,
    show_progress: bool = True,
    use_shared_transport: bool = False,
    http2: bool = True,
    retry_on_empty: bool = True,
    enable_scheduling: bool = False,
    max_pending_tasks: int = 1000,
    chunk_size: int = 100,
    enable_memory_optimization: bool = False,
    max_cache_size: int = 500,
    enable_memory_monitoring: bool = False,
    max_inputs: Optional[int] = None,
    skip_lines: int = 0,
    resume: bool = False,
    dataset_name: Optional[str] = None,
    subset: Optional[str] = None,
    split: str = "train",
    mapping: Optional[Dict[str, str]] = None,
    enable_profile: bool = False,
    profile_output_path: Optional[str] = None,
    profile_output_fields: Optional[List[str]] = None,
):
    """適応的並行性制御ストリーミングパイプライン実行（後方互換API）"""
    from .config import load_config

    cfg = load_config(yaml_path)
    run_config = RunConfig(
        concurrency=ConcurrencyConfig(
            adaptive=True,
            max_concurrent_limit=max_concurrent,
            min_concurrent=min_concurrent,
            target_latency_ms=target_latency_ms,
            target_queue_depth=target_queue_depth,
            metrics_type=metrics_type,
        ),
        io=IOConfig(),
        resume=ResumeConfig(
            resume=resume, skip_lines=skip_lines, max_inputs=max_inputs
        ),
        memory=MemoryConfig(
            enable_scheduling=enable_scheduling,
            max_pending_tasks=max_pending_tasks,
            chunk_size=chunk_size,
            enable_memory_optimization=enable_memory_optimization,
            max_cache_size=max_cache_size,
            enable_memory_monitoring=enable_memory_monitoring,
        ),
        profile=ProfileConfig(
            enable=enable_profile,
            output_path=profile_output_path,
            output_fields=profile_output_fields,
        ),
        transport=TransportConfig(
            use_shared_transport=use_shared_transport,
            http2=http2,
            retry_on_empty=retry_on_empty,
        ),
        data_source=DataSourceConfig(
            input_path=input_path,
            dataset_name=dataset_name,
            subset=subset,
            split=split,
            mapping=mapping,
        ),
        save_intermediate=save_intermediate,
        show_progress=show_progress,
    )
    engine = PipelineEngine(cfg, run_config)
    engine.run(output_path)


def run_streaming_adaptive_batched(
    yaml_path: str,
    input_path: Optional[str],
    output_path: str,
    max_concurrent: int = 64,
    min_concurrent: int = 1,
    target_latency_ms: int = 3000,
    target_queue_depth: int = 32,
    metrics_type: str = "none",
    max_batch_size: int = 32,
    max_wait_ms: int = 50,
    save_intermediate: bool = False,
    show_progress: bool = True,
    use_shared_transport: bool = False,
    http2: bool = True,
    retry_on_empty: bool = True,
    enable_scheduling: bool = False,
    max_pending_tasks: int = 1000,
    chunk_size: int = 100,
    enable_memory_optimization: bool = False,
    max_cache_size: int = 500,
    enable_memory_monitoring: bool = False,
    max_inputs: Optional[int] = None,
    skip_lines: int = 0,
    resume: bool = False,
    dataset_name: Optional[str] = None,
    subset: Optional[str] = None,
    split: str = "train",
    mapping: Optional[Dict[str, str]] = None,
    enable_profile: bool = False,
    profile_output_path: Optional[str] = None,
    profile_output_fields: Optional[List[str]] = None,
):
    """バッチング付き適応的並行性制御ストリーミングパイプライン実行（後方互換API）"""
    from .config import load_config

    cfg = load_config(yaml_path)
    run_config = RunConfig(
        concurrency=ConcurrencyConfig(
            adaptive=True,
            max_concurrent_limit=max_concurrent,
            min_concurrent=min_concurrent,
            target_latency_ms=target_latency_ms,
            target_queue_depth=target_queue_depth,
            metrics_type=metrics_type,
            enable_request_batching=True,
            max_batch_size=max_batch_size,
            max_wait_ms=max_wait_ms,
        ),
        io=IOConfig(),
        resume=ResumeConfig(
            resume=resume, skip_lines=skip_lines, max_inputs=max_inputs
        ),
        memory=MemoryConfig(
            enable_scheduling=enable_scheduling,
            max_pending_tasks=max_pending_tasks,
            chunk_size=chunk_size,
            enable_memory_optimization=enable_memory_optimization,
            max_cache_size=max_cache_size,
            enable_memory_monitoring=enable_memory_monitoring,
        ),
        profile=ProfileConfig(
            enable=enable_profile,
            output_path=profile_output_path,
            output_fields=profile_output_fields,
        ),
        transport=TransportConfig(
            use_shared_transport=use_shared_transport,
            http2=http2,
            retry_on_empty=retry_on_empty,
        ),
        data_source=DataSourceConfig(
            input_path=input_path,
            dataset_name=dataset_name,
            subset=subset,
            split=split,
            mapping=mapping,
        ),
        save_intermediate=save_intermediate,
        show_progress=show_progress,
    )
    engine = PipelineEngine(cfg, run_config)
    engine.run(output_path)


__all__ = [
    # I/O
    "AsyncBufferedWriter",
    "count_lines_fast",
    "read_jsonl",
    "read_csv",
    "read_hf_dataset",
    "apply_mapping",
    "write_jsonl",
    # Pipeline runners (後方互換API)
    "run_streaming",
    "run_streaming_adaptive",
    "run_streaming_adaptive_batched",
    "run",
    "test_run",
    # 新Public API
    "PipelineEngine",
    "RunConfig",
    "ConcurrencyConfig",
    "IOConfig",
    "ResumeConfig",
    "MemoryConfig",
    "ProfileConfig",
    "TransportConfig",
    "DataSourceConfig",
    "RunReport",
    "RowResult",
]
