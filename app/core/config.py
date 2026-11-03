from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


APPROVED_OPENROUTER_MODELS = {
    "qwen/qwen3-30b-a3b-instruct-2507",
    "deepseek/deepseek-chat-v3.1",
    "anthropic/claude-haiku-4.5",
    "openai/gpt-5-mini",
}

APPROVED_DEMO_IMAGE_MODELS = {
    "google/gemini-2.5-flash-image",
    "bytedance-seed/seedream-5-0-flash",
    "bytedance-seed/seedream-4.5",
}


class Settings(BaseSettings):
    app_name: str = "Lead Desk"
    app_version: str = "0.1.0"
    database_url: str = Field(alias="DATABASE_URL")

    auth_username: str = Field(alias="AUTH_USERNAME")
    auth_password_hash: str = Field(alias="AUTH_PASSWORD_HASH")
    auth_session_secret: str = Field(alias="AUTH_SESSION_SECRET")

    public_app_url: str = Field(
        default="https://lead-desk-alpha.vercel.app",
        alias="PUBLIC_APP_URL",
    )
    demo_site_root: str = Field(
        default="/var/www/lilos-demos",
        alias="DEMO_SITE_ROOT",
    )
    demo_site_base_url: str = Field(
        default="https://demo.lilosgrowth.com",
        alias="DEMO_SITE_BASE_URL",
    )
    demo_image_model: str = Field(
        default="google/gemini-2.5-flash-image",
        alias="DEMO_IMAGE_MODEL",
    )
    integration_encryption_key: str | None = Field(
        default=None,
        alias="INTEGRATION_ENCRYPTION_KEY",
    )

    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(
        default="qwen/qwen3-30b-a3b-instruct-2507",
        alias="OPENROUTER_MODEL",
    )

    gmail_client_id: str | None = Field(default=None, alias="GMAIL_CLIENT_ID")
    gmail_client_secret: str | None = Field(default=None, alias="GMAIL_CLIENT_SECRET")
    gmail_refresh_token: str | None = Field(default=None, alias="GMAIL_REFRESH_TOKEN")
    gmail_sender_email: str = Field(
        default="mike@lilosgrowth.com",
        alias="GMAIL_SENDER_EMAIL",
    )

    @field_validator("auth_session_secret")
    @classmethod
    def validate_auth_session_secret(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("AUTH_SESSION_SECRET must be at least 32 characters")
        return value

    @field_validator("auth_password_hash")
    @classmethod
    def validate_auth_password_hash(cls, value: str) -> str:
        if not value.startswith("pbkdf2_sha256$"):
            raise ValueError("AUTH_PASSWORD_HASH must use pbkdf2_sha256 format")
        return value

    @field_validator("openrouter_model")
    @classmethod
    def validate_openrouter_model(cls, value: str) -> str:
        if value not in APPROVED_OPENROUTER_MODELS:
            approved = ", ".join(sorted(APPROVED_OPENROUTER_MODELS))
            raise ValueError(
                f"OPENROUTER_MODEL must be an approved model: {approved}"
            )
        return value

    @field_validator("demo_image_model")
    @classmethod
    def validate_demo_image_model(cls, value: str) -> str:
        if value not in APPROVED_DEMO_IMAGE_MODELS:
            approved = ", ".join(sorted(APPROVED_DEMO_IMAGE_MODELS))
            raise ValueError(
                f"DEMO_IMAGE_MODEL must be an approved model: {approved}"
            )
        return value

    @field_validator("public_app_url", "demo_site_base_url")
    @classmethod
    def normalize_public_url(cls, value: str) -> str:
        value = value.rstrip("/")
        if not value.startswith("https://"):
            raise ValueError("public URLs must use https")
        return value

    @property
    def openrouter_configured(self) -> bool:
        return bool(self.openrouter_api_key and self.openrouter_model)

    @property
    def demo_image_generation_configured(self) -> bool:
        return bool(self.openrouter_api_key and self.demo_image_model)

    @property
    def gmail_legacy_configured(self) -> bool:
        return bool(
            self.gmail_client_id
            and self.gmail_client_secret
            and self.gmail_refresh_token
            and self.gmail_sender_email
        )

    @property
    def gmail_oauth_configured(self) -> bool:
        return bool(
            self.gmail_client_id
            and self.gmail_client_secret
            and self.integration_encryption_key
            and self.gmail_sender_email
            and self.public_app_url
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
