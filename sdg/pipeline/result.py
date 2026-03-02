"""sdg/pipeline/result.py - パイプライン実行結果型"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class RowResult:
    """1 行分の処理結果（不変）"""

    row_index: int
    data: Dict[str, Any]
    error: Optional[Exception] = None

    @property
    def success(self) -> bool:
        """エラーなしで完了した場合 True"""
        return self.error is None


@dataclass
class RunReport:
    """パイプライン全体の実行サマリー"""

    total_rows: int = 0
    completed_rows: int = 0
    error_rows: int = 0
    elapsed_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        """成功率（0.0 〜 1.0）"""
        if self.total_rows == 0:
            return 0.0
        return self.completed_rows / self.total_rows

    @property
    def skipped_rows(self) -> int:
        """未処理行数"""
        return self.total_rows - self.completed_rows - self.error_rows


__all__ = [
    "RowResult",
    "RunReport",
]
