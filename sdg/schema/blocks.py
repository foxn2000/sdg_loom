"""sdg/schema/blocks.py - ブロック定義 Pydantic モデル（discriminated union）"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class OutputDef(BaseModel):
    """AI 出力フィールド定義"""

    model_config = {"populate_by_name": True}

    name: str
    select: str = "full"  # full | tag | regex | jsonpath
    tag: Optional[str] = None
    regex: Optional[str] = None
    path: Optional[str] = None  # jsonpath
    join_with: Optional[str] = None
    type_hint: Optional[str] = None  # string|number|boolean|json
    # logic 出力用
    from_: Optional[str] = Field(
        None, alias="from"
    )  # boolean|value|join|count|any|all|first|last|list|var|accumulator
    var: Optional[str] = None
    source: Optional[str] = None


class BlockBase(BaseModel):
    """全ブロック共通フィールド"""

    model_config = {"populate_by_name": True}

    type: str
    exec: int = Field(default=0, ge=0)
    id: Optional[str] = None
    name: Optional[str] = None
    run_if: Any = None
    on_error: str = "fail"  # fail | continue | retry
    retry: Optional[Dict[str, Any]] = None
    budget: Optional[Dict[str, Any]] = None


class AIBlockConfig(BlockBase):
    """AI ブロック設定"""

    type: Literal["ai"] = "ai"
    model: str = ""
    system_prompt: Optional[str] = None
    prompts: List[str] = Field(default_factory=list)
    outputs: List[OutputDef] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    mode: str = "text"  # text | json
    save_to: Optional[Dict[str, Any]] = None


class LogicBlockConfig(BlockBase):
    """ロジックブロック設定"""

    type: Literal["logic"] = "logic"
    op: str = "if"  # if|and|or|not|for|while|recurse|set|let|reduce|call|emit
    # if/and/or/not
    cond: Any = None
    then: Optional[str] = None
    else_: Optional[str] = Field(None, alias="else")  # 'else' は予約語なので else_
    operands: Optional[List[Any]] = None
    # for
    list: Optional[str] = None
    parse: Optional[str] = None  # lines|csv|json|regex
    regex_pattern: Optional[str] = None
    var: Optional[str] = None
    drop_empty: Optional[bool] = None
    where: Any = None
    map: Optional[Union[str, Dict[str, Any]]] = None
    # while
    init: Optional[List[Dict[str, Any]]] = None
    step: Optional[List[Dict[str, Any]]] = None
    # recurse
    function: Optional[Union[str, Dict[str, Any]]] = None
    with_: Optional[Dict[str, Any]] = Field(
        None, alias="with"
    )  # 'with' は予約語なので with_
    returns: Optional[List[str]] = None
    # set/let
    value: Any = None
    bindings: Optional[Dict[str, Any]] = None
    body: Optional[List[Dict[str, Any]]] = None
    # 共通
    # NOTE: 'list' フィールドがクラス本体で Python 組み込み list を上書きするため
    #       lambda を使う（Field(default_factory=list) だと list=None になる）
    outputs: List[Dict[str, Any]] = Field(default_factory=lambda: [])


class PythonBlockConfig(BlockBase):
    """Python ブロック設定"""

    type: Literal["python"] = "python"
    function: str = ""  # v1 互換
    entrypoint: Optional[str] = None  # v2: function と同義
    inputs: Any = Field(default_factory=list)  # list or dict
    code_path: Optional[str] = None
    function_code: Optional[str] = None  # インラインコード
    venv_path: Optional[str] = None  # v1 互換（非推奨）
    outputs: List[str] = Field(default_factory=list)
    # v2 拡張
    use_env: str = "global"  # global | override
    override_env: Optional[Dict[str, Any]] = None
    timeout_ms: Optional[int] = None
    ctx_access: List[str] = Field(default_factory=list)


class EndBlockConfig(BlockBase):
    """終了ブロック設定"""

    type: Literal["end"] = "end"
    reason: Optional[str] = None
    exit_code: Optional[str] = None
    final: List[Dict[str, str]] = Field(default_factory=list)
    final_mode: str = "map"  # map | list
    include_vars: List[str] = Field(default_factory=list)


# discriminated union - type フィールドで判別
BlockConfig = Annotated[
    Union[AIBlockConfig, LogicBlockConfig, PythonBlockConfig, EndBlockConfig],
    Field(discriminator="type"),
]

__all__ = [
    "OutputDef",
    "BlockBase",
    "AIBlockConfig",
    "LogicBlockConfig",
    "PythonBlockConfig",
    "EndBlockConfig",
    "BlockConfig",
]
