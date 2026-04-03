"""Application configuration and settings."""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    env: str = Field(default="development", description="Environment: development, staging, production")
    debug: bool = Field(default=False, description="Debug mode")
    app_name: str = Field(default="email-ghl-pipeline", description="Application name")
    log_level: str = Field(default="INFO", description="Logging level")

    # API Keys
    claude_api_key: str = Field(default="", description="Anthropic Claude API key")
    ghl_api_key: str = Field(default="", description="GoHighLevel API key")
    ghl_location_id: str = Field(default="", description="GoHighLevel location ID")

    # IMAP Settings (email monitoring)
    imap_host: str = Field(default="", description="IMAP server hostname (e.g. mail.onixcap.net)")
    imap_port: int = Field(default=993, description="IMAP server port (993 for SSL)")
    imap_email: str = Field(default="", description="Email address to monitor (e.g. uwteam@onixcap.net)")
    imap_password: str = Field(default="", description="Email password or app password")

    # SMTP Settings (failure notifications)
    smtp_host: str = Field(default="", description="SMTP server hostname (often same as IMAP host)")
    smtp_port: int = Field(default=587, description="SMTP server port (587 for STARTTLS, 465 for SSL)")
    notification_email: str = Field(
        default="",
        description="Email to send failure notifications to (defaults to imap_email if empty)"
    )

    # GHL Settings
    source_documents_field_id: str = Field(
        default="",
        description="GHL custom field ID for the Source Documents FILE_UPLOAD field"
    )
    ghl_api_base_url: str = Field(
        default="https://rest.gohighlevel.com/v1",
        description="GHL API base URL"
    )

    # Database
    database_url: str = Field(
        default="sqlite:///./email_ghl.db",
        description="Database connection URL"
    )

    # Redis (optional)
    redis_url: Optional[str] = Field(default=None, description="Redis connection URL")

    # Claude Settings
    claude_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Claude model to use"
    )
    claude_max_tokens: int = Field(default=4000, description="Max tokens for Claude")
    claude_timeout: int = Field(default=60, description="Claude API timeout in seconds")

    # Processing Settings
    min_confidence_threshold: float = Field(
        default=0.25,
        description="Minimum confidence threshold for accepting extractions"
    )
    image_fingerprint_ttl_hours: int = Field(
        default=24,
        description="Hours to keep email fingerprints in cache"
    )
    extraction_cache_ttl_days: int = Field(
        default=7,
        description="Days to keep extraction records"
    )

    # Security
    webhook_secret: Optional[str] = Field(
        default=None,
        description="Webhook secret for validation"
    )

    # Monitoring
    sentry_dsn: Optional[str] = Field(default=None, description="Sentry DSN for error tracking")

    @property
    def effective_notification_email(self) -> str:
        """Return notification email, falling back to imap_email."""
        return self.notification_email or self.imap_email

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()
