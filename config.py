"""
設定読み込みモジュール

.env ファイルから設定を読み込み、型変換して提供する。
LM Studio 固有の名前を排除し、任意の OpenAI 互換バックエンドに対応。
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


@dataclass(frozen=True)
class AgentConfig:
    # LLM バックエンド接続（OpenAI 互換であれば何でも可）
    llm_base_url: str
    llm_api_key:  str
    model_name:   str

    # エージェント動作
    max_steps:    int
    temperature:  float
    verbose:      bool

    # ログ設定
    next_action_field: str   # ツール結果内の「次の推奨」フィールド名


def load_config() -> AgentConfig:
    """環境変数から AgentConfig を生成して返す"""
    return AgentConfig(
        llm_base_url       = os.getenv("LLM_BASE_URL",        "http://localhost:1234/v1"),
        llm_api_key        = os.getenv("LLM_API_KEY",         "lm-studio"),
        model_name         = os.getenv("MODEL_NAME",          "your-model-name"),
        max_steps          = int(os.getenv("MAX_STEPS",       "10")),
        temperature        = float(os.getenv("TEMPERATURE",   "0.1")),
        verbose            = os.getenv("VERBOSE", "true").lower() == "true",
        next_action_field  = os.getenv("NEXT_ACTION_FIELD",   "next_recommended_action"),
    )
