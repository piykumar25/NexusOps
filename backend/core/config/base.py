from typing import Any, Dict, Optional, Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
import json
import yaml
import os

class ConfigBase(BaseSettings):
    """Base configuration class with file loading support."""
    @classmethod
    def from_file(cls, path: str, **kwargs):
        if not os.path.exists(path):
            return cls(**kwargs)
            
        ext = path.split('.')[-1].lower()
        if ext in ('yaml', 'yml'):
            return cls.from_yaml(path, **kwargs)
        elif ext == 'json':
            return cls.from_json(path, **kwargs)
        raise ValueError(f"Unsupported config format: {ext}")
        
    @classmethod
    def from_yaml(cls, path: str, **kwargs):
        with open(path, 'r') as f:
            data = yaml.safe_load(f) or {}
        data.update(kwargs)
        return cls(**data)

    @classmethod
    def from_json(cls, path: str, **kwargs):
        with open(path, 'r') as f:
            data = json.load(f) or {}
        data.update(kwargs)
        return cls(**data)

class LLMConfig(ConfigBase):
    """Universal configuration object for LLM providers."""
    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_nested_delimiter="__",
    )
    
    provider: Literal["ollama", "azure", "openai"] = "openai"
    model_name: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    api_key: Optional[str] = None
    temperature: float = 0.0
    seed: Optional[int] = None
    max_tokens: Optional[int] = None
    api_version: str = "2024-02-15-preview"
    azure_endpoint: Optional[str] = None
    thinking_level: Optional[str] = None
    reasoning_effort: Optional[str] = None
    reasoning_summary: Optional[str] = None
    output_mode: Optional[str] = None
    log_path: str = "./logs"
    log_filename: Optional[str] = None
    retries: int = 3
    model_http_retries: int = 0
    model_http_retry_delay_seconds: float = 10.0
    disable_ssl_verification: bool = False
    extra_headers: Optional[Dict[str, str]] = None

    @property
    def effective_azure_endpoint(self) -> Optional[str]:
        return self.azure_endpoint or self.base_url
