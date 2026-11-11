from __future__ import annotations

import base64
import binascii
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KOMUTE_", extra="ignore")

    env: Literal["dev", "production"] = "dev"
    api_key: SecretStr
    storage_root: Path
    storage_key_b64: SecretStr
    storage_key_id: str
    manifest_key_b64: SecretStr
    manifest_key_id: str
    models_dir: Path = Path("backend/models")
    liveness_model: Path | None = None
    dev_skip_liveness: bool = False
    face_match_threshold: float = 0.40
    liveness_threshold: float = 0.5
    plate_min_confidence: float = 0.6
    max_upload_bytes: int = 10_000_000
    max_image_side: int = 2048
    retry_after_s: int = 5
    rejected_images_ttl_h: int = 72
    approved_originals_ttl_d: int = 30
    sweep_interval_s: int = 3600

    @field_validator("storage_key_b64", "manifest_key_b64")
    @classmethod
    def _key_is_32_bytes(cls, v: SecretStr) -> SecretStr:
        try:
            raw = base64.b64decode(v.get_secret_value(), validate=True)
        except (binascii.Error, ValueError) as e:
            raise ValueError("key must be valid base64") from e
        if len(raw) != 32:
            raise ValueError("key must decode to 32 bytes")
        return v

    @field_validator("storage_root")
    @classmethod
    def _not_onedrive(cls, v: Path) -> Path:
        # String check only (no filesystem access); splits on both separators.
        for part in re.split(r"[\\/]", str(v)):
            p = part.lower()
            if p == "onedrive" or p.startswith("onedrive - "):
                raise ValueError("storage_root must not be inside OneDrive")
        return v

    @model_validator(mode="after")
    def _production_rules(self) -> Settings:
        if self.env == "production":
            if self.dev_skip_liveness:
                raise ValueError("dev_skip_liveness is forbidden in production")
            if self.liveness_model is None:
                raise ValueError("liveness_model is required in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
