from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Lead Desk"
    app_version: str = "0.1.0"
    database_url: str = Field(alias="DATABASE_URL")

    auth_username: str = Field(alias="AUTH_USERNAME")
    auth_password_hash: str = Field(alias="AUTH_PASSWORD_HASH")
    auth_session_secret: str = Field(alias="AUTH_SESSION_SECRET")

    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(
        default="openai/gpt-chat-latest",
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

    @property
    def openrouter_configured(self) -> bool:
        return bool(self.openrouter_api_key and self.openrouter_model)

    @property
    def gmail_configured(self) -> bool:
        return bool(
            self.gmail_client_id
            and self.gmail_client_secret
            and self.gmail_refresh_token
            and self.gmail_sender_email
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
