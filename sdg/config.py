"""sdg/config.py - 後方互換レイヤー

既存の executors / runners / cli が以下のパターンでインポートしている:
    from sdg.config import load_config, SDGConfig, AIBlock, LogicBlock, ...

このモジュールは sdg.schema からすべてを再エクスポートし、
古い名前 (AIBlock, LogicBlock, PyBlock, EndBlock, Block ...) も
引き続き使えるよう alias を定義する。

isinstance(block, AIBlock) などのチェックも引き続き動作する。

Note:
    - 実際の Pydantic モデル定義は sdg/schema/ 配下に存在する。
    - このモジュールはエイリアス・再エクスポート専用であり、新しい型定義は行わない。
    - AIBlock, LogicBlock, PyBlock, EndBlock は executors で使用中のため維持。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# schema から Pydantic モデルを再エクスポート（実体）
# ---------------------------------------------------------------------------

from .schema.blocks import (
    AIBlockConfig,
    BlockBase,
    BlockConfig,
    EndBlockConfig,
    LogicBlockConfig,
    OutputDef,
    PythonBlockConfig,
)
from .schema.config import (
    BudgetConfig,
    Connection,
    FileDef,
    FunctionDef,
    GlobalsConfig,
    ImageDef,
    ModelConfig,
    RuntimeConfig,
    SDGConfig,
    TemplateDef,
)

# ---------------------------------------------------------------------------
# 後方互換エイリアス - 旧名称で isinstance が動作するよう同一クラス参照
# これらは executors / runners / cli で参照されているため削除禁止
# ---------------------------------------------------------------------------

#: 旧 Block dataclass → Pydantic BlockBase
Block = BlockBase

#: 旧 AIBlock dataclass → Pydantic AIBlockConfig
AIBlock = AIBlockConfig

#: 旧 LogicBlock dataclass → Pydantic LogicBlockConfig
LogicBlock = LogicBlockConfig

#: 旧 PyBlock dataclass → Pydantic PythonBlockConfig
PyBlock = PythonBlockConfig

#: 旧 EndBlock dataclass → Pydantic EndBlockConfig
EndBlock = EndBlockConfig


# ---------------------------------------------------------------------------
# load_config - 旧 API 互換
# ---------------------------------------------------------------------------


def load_config(path: str) -> SDGConfig:
    """YAML ブループリントを読み込み SDGConfig を返す。

    旧 API 互換ラッパー。内部では SDGConfig.from_yaml に委譲する。
    """
    return SDGConfig.from_yaml(path)


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------

__all__ = [
    # 後方互換エイリアス（旧名称 → schema の型への参照）
    "Block",
    "AIBlock",
    "LogicBlock",
    "PyBlock",
    "EndBlock",
    # そのまま使用する型
    "OutputDef",
    "BlockConfig",
    # 設定クラス（実体は sdg.schema.config）
    "RuntimeConfig",
    "BudgetConfig",
    "GlobalsConfig",
    "FunctionDef",
    "ModelConfig",
    "TemplateDef",
    "FileDef",
    "ImageDef",
    "Connection",
    "SDGConfig",
    # 関数
    "load_config",
]
