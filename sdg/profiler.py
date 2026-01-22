"""
生成後プロファイル収集モジュール

データ生成完了後のメトリクス収集と分析を行う。
- 言語分布
- 長さ分布
- 重複率
- パース失敗率
- 検証落ち率
- モデル別トークン使用量
"""
from __future__ import annotations
import hashlib
import json
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# langdetectは遅延インポート（オプショナル依存）
_langdetect_available = False
try:
    from langdetect import detect, LangDetectException
    _langdetect_available = True
except ImportError:
    pass


@dataclass
class LLMUsageStats:
    """モデル別LLM使用統計"""
    model_name: str
    call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latencies_ms: List[int] = field(default_factory=list)
    errors: int = 0

    @property
    def avg_latency_ms(self) -> float:
        """平均レイテンシ"""
        if not self.latencies_ms:
            return 0.0
        return statistics.mean(self.latencies_ms)

    @property
    def p50_latency_ms(self) -> float:
        """50パーセンタイルレイテンシ"""
        if not self.latencies_ms:
            return 0.0
        return statistics.median(self.latencies_ms)

    @property
    def p95_latency_ms(self) -> float:
        """95パーセンタイルレイテンシ"""
        if len(self.latencies_ms) < 2:
            return self.avg_latency_ms
        sorted_lat = sorted(self.latencies_ms)
        idx = int(len(sorted_lat) * 0.95)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]

    @property
    def p99_latency_ms(self) -> float:
        """99パーセンタイルレイテンシ"""
        if len(self.latencies_ms) < 2:
            return self.avg_latency_ms
        sorted_lat = sorted(self.latencies_ms)
        idx = int(len(sorted_lat) * 0.99)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "model_name": self.model_name,
            "call_count": self.call_count,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "errors": self.errors,
            "latency": {
                "avg_ms": round(self.avg_latency_ms, 2),
                "p50_ms": round(self.p50_latency_ms, 2),
                "p95_ms": round(self.p95_latency_ms, 2),
                "p99_ms": round(self.p99_latency_ms, 2),
            }
        }


@dataclass
class OutputQualityStats:
    """出力品質統計"""
    total_outputs: int = 0
    parse_failures: int = 0
    validation_failures: int = 0
    empty_outputs: int = 0

    @property
    def parse_failure_rate(self) -> float:
        """パース失敗率"""
        if self.total_outputs == 0:
            return 0.0
        return self.parse_failures / self.total_outputs

    @property
    def validation_failure_rate(self) -> float:
        """検証失敗率"""
        if self.total_outputs == 0:
            return 0.0
        return self.validation_failures / self.total_outputs

    @property
    def empty_output_rate(self) -> float:
        """空出力率"""
        if self.total_outputs == 0:
            return 0.0
        return self.empty_outputs / self.total_outputs

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "total_outputs": self.total_outputs,
            "parse_failures": self.parse_failures,
            "parse_failure_rate": round(self.parse_failure_rate, 4),
            "validation_failures": self.validation_failures,
            "validation_failure_rate": round(self.validation_failure_rate, 4),
            "empty_outputs": self.empty_outputs,
            "empty_output_rate": round(self.empty_output_rate, 4),
        }


class ProfileCollector:
    """
    生成後プロファイル収集クラス

    データ生成中にメトリクスを収集し、完了後にプロファイルを生成する。

    Example:
        collector = ProfileCollector()

        # 生成中にメトリクスを記録
        collector.record_llm_call("gpt-4", prompt_tokens=100, completion_tokens=50, latency_ms=500)
        collector.record_output("生成されたテキスト", output_field="answer")

        # 最終プロファイルを取得
        profile = collector.get_profile()
    """

    def __init__(
        self,
        detect_language: bool = True,
        detect_duplicates: bool = True,
        output_fields: Optional[List[str]] = None,
    ):
        """
        ProfileCollectorを初期化する。

        Args:
            detect_language: 言語検出を有効にするか
            detect_duplicates: 重複検出を有効にするか
            output_fields: 分析対象の出力フィールド名リスト（Noneの場合は全フィールド）
        """
        self._detect_language = detect_language and _langdetect_available
        self._detect_duplicates = detect_duplicates
        self._output_fields = output_fields

        # 処理統計
        self._start_time: Optional[float] = None
        self._end_time: Optional[float] = None
        self._total_rows: int = 0
        self._completed_rows: int = 0
        self._error_rows: int = 0

        # LLM使用統計（モデル別）
        self._llm_stats: Dict[str, LLMUsageStats] = defaultdict(
            lambda: LLMUsageStats(model_name="")
        )

        # 出力品質統計
        self._quality_stats = OutputQualityStats()

        # 言語分布
        self._language_counts: Counter = Counter()

        # 長さ分布
        self._output_lengths: List[int] = []

        # 重複検出用ハッシュセット
        self._content_hashes: Set[str] = set()
        self._duplicate_count: int = 0

    def start(self, total_rows: Optional[int] = None):
        """プロファイル収集を開始する"""
        self._start_time = time.time()
        if total_rows is not None:
            self._total_rows = total_rows

    def stop(self):
        """プロファイル収集を停止する"""
        self._end_time = time.time()

    def record_llm_call(
        self,
        model_name: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: int = 0,
        error: bool = False,
    ):
        """
        LLM呼び出しを記録する。

        Args:
            model_name: モデル名
            prompt_tokens: プロンプトトークン数
            completion_tokens: 生成トークン数
            latency_ms: レイテンシ（ミリ秒）
            error: エラーが発生したか
        """
        stats = self._llm_stats[model_name]
        stats.model_name = model_name
        stats.call_count += 1
        stats.prompt_tokens += prompt_tokens
        stats.completion_tokens += completion_tokens
        stats.total_tokens += prompt_tokens + completion_tokens
        if latency_ms > 0:
            stats.latencies_ms.append(latency_ms)
        if error:
            stats.errors += 1

    def record_output(
        self,
        output_data: Dict[str, Any],
        error: Optional[Exception] = None,
    ):
        """
        出力データを記録する。

        Args:
            output_data: 出力データ辞書
            error: エラー（あれば）
        """
        self._quality_stats.total_outputs += 1

        if error:
            self._error_rows += 1
            # エラーの種類によって分類
            error_str = str(error).lower()
            if "json" in error_str or "parse" in error_str:
                self._quality_stats.parse_failures += 1
            elif "valid" in error_str:
                self._quality_stats.validation_failures += 1
            return

        self._completed_rows += 1

        # 分析対象フィールドを抽出
        fields_to_analyze = self._output_fields or list(output_data.keys())

        for field_name in fields_to_analyze:
            if field_name.startswith("_"):  # 内部フィールドはスキップ
                continue

            content = output_data.get(field_name)
            if content is None:
                continue

            content_str = str(content)

            # 空出力チェック
            if not content_str.strip():
                self._quality_stats.empty_outputs += 1
                continue

            # 長さ記録
            self._output_lengths.append(len(content_str))

            # 言語検出
            if self._detect_language:
                lang = self._detect_language_safe(content_str)
                if lang:
                    self._language_counts[lang] += 1

            # 重複検出
            if self._detect_duplicates:
                content_hash = hashlib.md5(content_str.encode()).hexdigest()
                if content_hash in self._content_hashes:
                    self._duplicate_count += 1
                else:
                    self._content_hashes.add(content_hash)

    def record_row_result(
        self,
        row_index: int,
        output_data: Dict[str, Any],
        error: Optional[Exception] = None,
    ):
        """
        行単位の結果を記録する（StreamingResult互換）。

        Args:
            row_index: 行インデックス
            output_data: 出力データ
            error: エラー（あれば）
        """
        self.record_output(output_data, error)

    def _detect_language_safe(self, text: str) -> Optional[str]:
        """安全な言語検出（エラー時はNone）"""
        if not self._detect_language or not text.strip():
            return None
        try:
            # 短すぎるテキストは検出精度が低いのでスキップ
            if len(text) < 20:
                return None
            return detect(text)
        except Exception:
            return None

    @property
    def duration_seconds(self) -> float:
        """処理時間（秒）"""
        if self._start_time is None:
            return 0.0
        end = self._end_time or time.time()
        return end - self._start_time

    @property
    def rows_per_second(self) -> float:
        """秒あたりの処理行数"""
        duration = self.duration_seconds
        if duration == 0:
            return 0.0
        return self._completed_rows / duration

    @property
    def duplicate_rate(self) -> float:
        """重複率"""
        total = len(self._content_hashes) + self._duplicate_count
        if total == 0:
            return 0.0
        return self._duplicate_count / total

    def get_length_stats(self) -> Dict[str, Any]:
        """長さ統計を取得"""
        if not self._output_lengths:
            return {
                "count": 0,
                "min": 0,
                "max": 0,
                "avg": 0.0,
                "p50": 0.0,
                "p95": 0.0,
            }

        sorted_lengths = sorted(self._output_lengths)
        return {
            "count": len(self._output_lengths),
            "min": min(self._output_lengths),
            "max": max(self._output_lengths),
            "avg": round(statistics.mean(self._output_lengths), 2),
            "p50": round(statistics.median(self._output_lengths), 2),
            "p95": sorted_lengths[int(len(sorted_lengths) * 0.95)] if len(sorted_lengths) >= 2 else sorted_lengths[-1],
        }

    def get_language_distribution(self) -> Dict[str, Any]:
        """言語分布を取得"""
        total = sum(self._language_counts.values())
        if total == 0:
            return {"detected": False, "distribution": {}}

        distribution = {}
        for lang, count in self._language_counts.most_common():
            distribution[lang] = {
                "count": count,
                "rate": round(count / total, 4),
            }

        return {
            "detected": True,
            "total_detected": total,
            "distribution": distribution,
        }

    def get_profile(self) -> Dict[str, Any]:
        """
        完全なプロファイルを取得する。

        Returns:
            プロファイル辞書
        """
        # LLM統計をまとめる
        llm_summary = {
            "total_calls": sum(s.call_count for s in self._llm_stats.values()),
            "total_prompt_tokens": sum(s.prompt_tokens for s in self._llm_stats.values()),
            "total_completion_tokens": sum(s.completion_tokens for s in self._llm_stats.values()),
            "total_tokens": sum(s.total_tokens for s in self._llm_stats.values()),
            "total_errors": sum(s.errors for s in self._llm_stats.values()),
            "by_model": {
                name: stats.to_dict()
                for name, stats in self._llm_stats.items()
            },
        }

        return {
            "processing": {
                "total_rows": self._total_rows or self._quality_stats.total_outputs,
                "completed_rows": self._completed_rows,
                "error_rows": self._error_rows,
                "duration_seconds": round(self.duration_seconds, 2),
                "rows_per_second": round(self.rows_per_second, 2),
            },
            "llm_usage": llm_summary,
            "output_quality": self._quality_stats.to_dict(),
            "length_distribution": self.get_length_stats(),
            "language_distribution": self.get_language_distribution(),
            "duplicates": {
                "unique_outputs": len(self._content_hashes),
                "duplicate_count": self._duplicate_count,
                "duplicate_rate": round(self.duplicate_rate, 4),
            },
        }

    def to_json(self, indent: int = 2) -> str:
        """JSON文字列として出力"""
        return json.dumps(self.get_profile(), ensure_ascii=False, indent=indent)

    def save_to_file(self, path: str):
        """ファイルに保存"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
