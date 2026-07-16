from __future__ import annotations


def test_default_asr_profile_uses_turbo_with_conservative_batching(monkeypatch) -> None:
    # Given: no operator override for the ASR profile.
    monkeypatch.delenv("APP_WHISPERX_MODEL_NAME", raising=False)
    monkeypatch.delenv("APP_WHISPERX_BATCH_SIZE", raising=False)

    from app.settings import Settings

    # When: the application resolves its default settings.
    settings = Settings()

    # Then: long-form jobs use the lower-pressure GPU ASR profile.
    assert settings.whisperx_model_name == "turbo"
    assert settings.whisperx_batch_size == 8


def test_deepseek_proofread_settings_have_safe_operator_defaults(monkeypatch) -> None:
    # Given: no DeepSeek environment overrides.
    for name in (
        "APP_PROOFREAD_PROVIDER",
        "APP_DEEPSEEK_API_KEY",
        "APP_DEEPSEEK_BASE_URL",
        "APP_DEEPSEEK_MODEL",
        "APP_DEEPSEEK_REQUEST_TIMEOUT_SECONDS",
        "APP_DEEPSEEK_MAX_SEGMENTS_PER_REQUEST",
        "APP_DEEPSEEK_MAX_RETRIES",
    ):
        monkeypatch.delenv(name, raising=False)

    from app.settings import Settings

    # When: the backend resolves proofread configuration.
    settings = Settings()

    # Then: defaults are backend-only and preserve the documented provider limits.
    assert settings.proofread_provider == "deepseek"
    assert settings.deepseek_api_key is None
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.deepseek_model == "deepseek-v4-flash"
    assert settings.deepseek_request_timeout_seconds == 120
    assert settings.deepseek_max_segments_per_request == 80
    assert settings.deepseek_max_retries == 3


def test_deepseek_api_key_is_redacted_from_settings_representations(monkeypatch) -> None:
    # Given: an operator configures a DeepSeek API key through the environment.
    monkeypatch.setenv("APP_DEEPSEEK_API_KEY", "test-deepseek-key")

    from app.settings import Settings

    # When: settings are instantiated and serialized for diagnostics.
    settings = Settings()

    # Then: the secret is not exposed in repr or serialized settings output.
    assert "test-deepseek-key" not in repr(settings)
    assert "test-deepseek-key" not in repr(settings.model_dump())
    assert "test-deepseek-key" not in settings.model_dump(mode="json")["deepseek_api_key"]
