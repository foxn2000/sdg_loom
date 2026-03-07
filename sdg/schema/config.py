"""sdg/schema/config.py - メイン設定 Pydantic モデル"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

from .blocks import (
    AIBlockConfig,
    BlockBase,
    EndBlockConfig,
    LogicBlockConfig,
    OutputDef,
    PythonBlockConfig,
)


# ---------------------------------------------------------------------------
# ユーティリティ（循環インポート回避のため局所定義）
# ---------------------------------------------------------------------------


def _ensure_json_obj(v: Any) -> Any:
    """dict または JSON 文字列を dict に変換、None や空文字は {} を返す。"""
    import json

    if v is None:
        return {}
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v.strip():
        return json.loads(v)
    return {}


_ENV_PATTERN = re.compile(r"^\$\{ENV\.([^}]+)\}$")


# ---------------------------------------------------------------------------
# 設定クラス群
# ---------------------------------------------------------------------------


class MABELConfig(BaseModel):
    """MABEL メタデータ設定"""

    model_config = {"populate_by_name": True, "extra": "allow"}

    version: str = "1.0"
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None


class RuntimeConfig(BaseModel):
    """v2: 実行時環境設定"""

    model_config = {"populate_by_name": True}

    python: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RuntimeConfig":
        return cls(python=d.get("python", {}))


class BudgetConfig(BaseModel):
    """v2: 予算（安全停止）設定"""

    model_config = {"populate_by_name": True}

    loops: Dict[str, Any] = Field(default_factory=dict)
    recursion: Dict[str, Any] = Field(default_factory=dict)
    wall_time_ms: Optional[int] = None
    ai: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BudgetConfig":
        return cls(
            loops=d.get("loops", {"max_iters": 10000, "on_exceed": "error"}),
            recursion=d.get("recursion", {"max_depth": 256, "on_exceed": "error"}),
            wall_time_ms=d.get("wall_time_ms"),
            ai=d.get("ai", {}),
        )


class GlobalsConfig(BaseModel):
    """v2: グローバル変数/定数"""

    model_config = {"populate_by_name": True}

    const: Dict[str, Any] = Field(default_factory=dict)
    vars: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GlobalsConfig":
        return cls(const=d.get("const", {}), vars=d.get("vars", {}))


class FunctionDef(BaseModel):
    """v2: ユーザ定義関数"""

    model_config = {"populate_by_name": True}

    name: str
    args: List[str] = Field(default_factory=list)
    returns: List[str] = Field(default_factory=list)
    body: Any = None  # logic 関数: ステップリスト、python 関数: コード

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FunctionDef":
        return cls(
            name=d["name"],
            args=d.get("args", []),
            returns=d.get("returns", []),
            body=d.get("body"),
        )


class ModelConfig(BaseModel):
    """モデル定義（api_key の ${ENV.NAME} 解決を含む）"""

    model_config = {"populate_by_name": True}

    name: str
    api_model: str
    api_key: str
    base_url: Optional[str] = None
    organization: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    request_defaults: Dict[str, Any] = Field(default_factory=dict)
    capabilities: List[str] = Field(default_factory=list)
    safety: Dict[str, Any] = Field(default_factory=dict)
    # Reasoning 関連
    enable_reasoning: bool = False
    reasoning_effort: Optional[str] = None
    reasoning_max_tokens: Optional[int] = None
    include_reasoning: bool = True
    exclude_reasoning: bool = False
    # OpenRouter プロバイダールーティング設定
    provider: Optional[Dict[str, Any]] = None

    @field_validator("api_key", mode="before")
    @classmethod
    def resolve_env_api_key(cls, v: Any) -> Any:
        """${ENV.NAME} 形式の環境変数参照を解決する"""
        if isinstance(v, str):
            m = _ENV_PATTERN.match(v)
            if m:
                env_name = m.group(1)
                return os.environ.get(env_name, v)
        return v


class TemplateDef(BaseModel):
    """v2: 文字列テンプレート"""

    model_config = {"populate_by_name": True}

    name: str
    text: str


class FileDef(BaseModel):
    """v2: 埋め込みファイル"""

    model_config = {"populate_by_name": True}

    name: str
    mime: str
    content: str


class ImageDef(BaseModel):
    """v2.1: 画像定義"""

    model_config = {"populate_by_name": True}

    name: str
    path: Optional[str] = None
    url: Optional[str] = None
    base64: Optional[str] = None
    media_type: str = "image/png"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ImageDef":
        return cls(
            name=d["name"],
            path=d.get("path"),
            url=d.get("url"),
            base64=d.get("base64"),
            media_type=d.get("media_type", "image/png"),
        )


class Connection(BaseModel):
    """明示配線"""

    model_config = {"populate_by_name": True}

    from_: str = Field(alias="from")  # 'from' は予約語なので from_
    output: str
    to: str
    input: str


# ---------------------------------------------------------------------------
# ブロック正規化ヘルパー（YAML dict → 型付きブロックオブジェクト）
# ---------------------------------------------------------------------------


def _normalize_output(d: Dict[str, Any]) -> OutputDef:
    """出力定義を正規化"""
    return OutputDef(
        name=d["name"],
        select=d.get("select", "full"),
        tag=d.get("tag"),
        regex=d.get("regex"),
        path=d.get("path"),
        join_with=d.get("join_with"),
        type_hint=d.get("type_hint"),
        from_=d.get("from"),
        var=d.get("var"),
        source=d.get("source"),
    )


def _normalize_block(d: Dict[str, Any]) -> BlockBase:
    """YAML dict からブロックオブジェクトを生成"""
    typ = d.get("type")
    common: Dict[str, Any] = {
        "type": typ,
        "exec": int(d.get("exec", 0)),
        "id": d.get("id"),
        "name": d.get("name"),
        "run_if": _ensure_json_obj(d.get("run_if")),
        "on_error": d.get("on_error", "fail"),
        "retry": d.get("retry"),
        "budget": d.get("budget"),
    }

    if typ == "ai":
        outs = [_normalize_output(o) for o in d.get("outputs", [])]
        return AIBlockConfig(
            outputs=outs,
            model=d.get("model", ""),
            system_prompt=d.get("system_prompt"),
            prompts=list(d.get("prompts", [])),
            params=d.get("params", {}),
            attachments=d.get("attachments", []),
            mode=d.get("mode", "text"),
            save_to=d.get("save_to"),
            **common,
        )

    if typ == "logic":
        return LogicBlockConfig(
            op=d.get("op", "if"),
            cond=_ensure_json_obj(d.get("cond")),
            then=d.get("then"),
            else_=d.get("else"),
            operands=d.get("operands"),
            list=d.get("list"),
            parse=d.get("parse"),
            regex_pattern=d.get("regex_pattern"),
            var=d.get("var"),
            drop_empty=d.get("drop_empty"),
            where=_ensure_json_obj(d.get("where")),
            map=d.get("map"),
            init=d.get("init"),
            step=d.get("step"),
            function=d.get("function"),
            with_=d.get("with"),
            returns=d.get("returns"),
            value=d.get("value"),
            bindings=d.get("bindings"),
            body=d.get("body"),
            outputs=d.get("outputs", []),
            **common,
        )

    if typ == "python":
        return PythonBlockConfig(
            function=d.get("function", ""),
            entrypoint=d.get("entrypoint"),
            inputs=d.get("inputs", []),
            code_path=d.get("code_path"),
            function_code=d.get("function_code"),
            venv_path=d.get("venv_path"),
            outputs=d.get("outputs", []),
            use_env=d.get("use_env", "global"),
            override_env=d.get("override_env"),
            timeout_ms=d.get("timeout_ms"),
            ctx_access=d.get("ctx_access", []),
            **common,
        )

    if typ == "end":
        return EndBlockConfig(
            reason=d.get("reason"),
            exit_code=d.get("exit_code"),
            final=d.get("final", []),
            final_mode=d.get("final_mode", "map"),
            include_vars=d.get("include_vars", []),
            **common,
        )

    raise ValueError(f"Unsupported block type: {typ}")


# ---------------------------------------------------------------------------
# メイン設定クラス
# ---------------------------------------------------------------------------


class SDGConfig(BaseModel):
    """SDG メイン設定（YAML ブループリント全体）"""

    model_config = {"populate_by_name": True, "arbitrary_types_allowed": True}

    mabel: MABELConfig = Field(default_factory=MABELConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)
    globals_: GlobalsConfig = Field(default_factory=GlobalsConfig)
    functions: Dict[str, List[FunctionDef]] = Field(default_factory=dict)
    models: List[ModelConfig] = Field(default_factory=list)
    templates: List[TemplateDef] = Field(default_factory=list)
    files: List[FileDef] = Field(default_factory=list)
    images: List[ImageDef] = Field(default_factory=list)
    blocks: List[BlockBase] = Field(default_factory=list)
    connections: List[Connection] = Field(default_factory=list)
    # 実行時に外部から設定される最適化オプション
    optimization: Dict[str, Any] = Field(default_factory=dict)

    # ------------------------------------------------------------------
    # 検索メソッド
    # ------------------------------------------------------------------

    def model_by_name(self, name: str) -> ModelConfig:
        for m in self.models:
            if m.name == name:
                return m
        raise KeyError(f"Model not found: {name}")

    def image_by_name(self, name: str) -> Optional[ImageDef]:
        """画像定義を名前で取得"""
        for img in self.images:
            if img.name == name:
                return img
        return None

    def get_version(self) -> str:
        """MABEL バージョンを取得"""
        return self.mabel.version

    def is_v2(self) -> bool:
        """v2 仕様かどうか（v2.1 も含む）"""
        return self.get_version().startswith("2.")

    # ------------------------------------------------------------------
    # ファクトリ
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: str) -> "SDGConfig":
        """YAML ファイルから SDGConfig を生成"""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # MABEL 情報
        mabel: MABELConfig = MABELConfig(**(data.get("mabel", {}) or {}))

        # v2 拡張フィールド
        runtime = RuntimeConfig.from_dict(data.get("runtime", {}))
        budgets = BudgetConfig.from_dict(data.get("budgets", {}))
        globals_ = GlobalsConfig.from_dict(data.get("globals", {}))

        # 関数定義
        functions: Dict[str, List[FunctionDef]] = {}
        if "functions" in data:
            funcs_data = data["functions"]
            if "logic" in funcs_data:
                functions["logic"] = [
                    FunctionDef.from_dict(f) for f in funcs_data["logic"]
                ]
            if "python" in funcs_data:
                functions["python"] = [
                    FunctionDef.from_dict(f) for f in funcs_data["python"]
                ]

        # モデル（api_key の ENV 解決は validator で実行）
        models = [ModelConfig(**m) for m in data.get("models", [])]

        # テンプレート
        templates = [TemplateDef(**t) for t in data.get("templates", [])]

        # ファイル
        files = [FileDef(**f) for f in data.get("files", [])]

        # 画像（v2.1）
        images = [ImageDef.from_dict(img) for img in data.get("images", [])]

        # ブロック
        blocks_raw = [_normalize_block(b) for b in data.get("blocks", [])]
        blocks = sorted(blocks_raw, key=lambda b: b.exec)

        # 接続
        connections = []
        for c in data.get("connections", []):
            connections.append(
                Connection.model_validate(
                    {
                        "from": c["from"],
                        "output": c["output"],
                        "to": c["to"],
                        "input": c["input"],
                    }
                )
            )

        cfg = cls(
            mabel=mabel,
            runtime=runtime,
            budgets=budgets,
            globals_=globals_,
            functions=functions,
            models=models,
            templates=templates,
            files=files,
            images=images,
            blocks=blocks,
            connections=connections,
        )

        # 基本検証
        for b in cfg.blocks:
            if b.type == "ai" and not isinstance(b, AIBlockConfig):
                raise ValueError("Block casting failed for ai")
            if b.type == "ai" and not getattr(b, "model", ""):
                raise ValueError("ai block requires 'model'")
            if b.type == "python":
                if not (getattr(b, "function", "") or getattr(b, "entrypoint", None)):
                    raise ValueError("python block requires 'function' or 'entrypoint'")

        return cfg


__all__ = [
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
]
