from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .exceptions import ConfigError


class ModelConfig(BaseModel):
    provider: str = "openai_compatible"
    api_key_env: str = "LC_AUTO_MODEL_API_KEY"
    base_url_env: str = "LC_AUTO_MODEL_BASE_URL"
    model_env: str = "LC_AUTO_MODEL_NAME"
    base_url: str | None = None
    model: str | None = None
    temperature: float = 0.2
    timeout_seconds: int = 90

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return value.strip().lower()

    @model_validator(mode="after")
    def apply_env(self) -> "ModelConfig":
        if not self.base_url:
            self.base_url = os.getenv(self.base_url_env, "https://api.openai.com/v1")
        if not self.model:
            self.model = os.getenv(self.model_env, "")
        return self

    @property
    def api_key(self) -> str:
        return os.getenv(self.api_key_env, "")

    def validate_for_runtime(self) -> None:
        if self.provider == "fake":
            return
        if self.provider != "openai_compatible":
            raise ConfigError(f"Unsupported model provider: {self.provider}")
        if not self.api_key:
            raise ConfigError(f"Missing model API key env var: {self.api_key_env}")
        if not self.model:
            raise ConfigError(f"Missing model name env var or config value: {self.model_env}")
        if not self.base_url:
            raise ConfigError("Missing model base_url")


class AppConfig(BaseModel):
    site: str = "leetcode.cn"
    language: str = "python3"
    allow_real_submit: bool = False
    run_before_submit: bool = False
    max_questions_per_run: int = Field(default=3, ge=1)
    max_repairs_per_problem: int = Field(default=3, ge=0)
    browser_profile_dir: Path = Path("./.browser-profile")
    browser_cdp_url: str | None = None
    state_db_path: Path = Path("./lc_auto.sqlite3")
    headless: bool = False
    slow_mo_ms: int = Field(default=50, ge=0)
    navigation_timeout_ms: int = Field(default=45000, ge=5000)
    judge_timeout_ms: int = Field(default=120000, ge=10000)
    min_delay_seconds: int = Field(default=60, ge=0)
    max_delay_seconds: int = Field(default=180, ge=0)
    stop_on_security_challenge: bool = True
    skip_accepted: bool = True
    continue_on_problem_error: bool = False
    artifact_dir: Path = Path("./artifacts")
    save_screenshots: bool = True
    save_page_html: bool = False
    problemset_scroll_rounds: int = Field(default=12, ge=1)
    model: ModelConfig = Field(default_factory=ModelConfig)

    @field_validator("site")
    @classmethod
    def validate_site(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "leetcode.cn":
            raise ValueError("MVP only supports leetcode.cn")
        return normalized

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"python3", "python"}:
            raise ValueError("MVP only supports Python3")
        return "python3"

    @model_validator(mode="after")
    def validate_delay_range(self) -> "AppConfig":
        if self.max_delay_seconds < self.min_delay_seconds:
            raise ValueError("max_delay_seconds must be >= min_delay_seconds")
        return self


def load_config(path: str | Path | None = None, env_path: str | Path | None = ".env") -> AppConfig:
    if env_path:
        load_dotenv(env_path)

    config_path = Path(path) if path else Path("config.yaml")
    data: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        if not isinstance(loaded, dict):
            raise ConfigError(f"Config file must contain a mapping: {config_path}")
        data = loaded
    elif path:
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        return AppConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc
