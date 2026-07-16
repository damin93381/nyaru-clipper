from __future__ import annotations

import shlex
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", extra="ignore")

    cors_allowed_origin_regex: str = (
        r"^https?://(localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
        r"172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2})(?::\d+)?$"
    )

    bilibili_cookie_path: Path | None = None
    local_import_roots: str = ""
    bbdown_binary: str = "BBDown"
    bbdown_extra_args: str = ""
    ytdlp_binary: str = "yt-dlp"
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    export_video_backend: Literal["cpu", "windows-amf"] = "cpu"
    windows_ffmpeg_binary: Path | None = None
    whisperx_model_name: str | None = "turbo"
    whisperx_alignment_model_name: str | None = None
    whisperx_device: str = "cuda"
    whisperx_compute_type: str = "float16"
    whisperx_language: str = "zh"
    whisperx_batch_size: int = 8
    whisperx_model_cache_dir: Path | None = None
    translation_provider: str = "hf"
    translation_model_name: str = "facebook/nllb-200-distilled-600M"
    translation_fallback_model_name: str | None = None
    translation_device: str = "cuda"
    translation_source_language_code: str = "zho_Hans"
    translation_target_language_code: str = "jpn_Jpan"
    translation_max_new_tokens: int = 256
    proofread_provider: Literal["deepseek"] = "deepseek"
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_request_timeout_seconds: float = 120
    deepseek_max_segments_per_request: int = 80
    deepseek_max_retries: int = 3
    scenedetect_threshold: float = 27.0
    scenedetect_min_scene_len: int = 15


def get_settings() -> Settings:
    return Settings()


def get_bbdown_extra_args(settings: Settings) -> list[str]:
    return shlex.split(settings.bbdown_extra_args)
