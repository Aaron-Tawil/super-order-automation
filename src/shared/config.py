from typing import List, Optional

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.shared import constants


class Settings(BaseSettings):
    """
    Centralized configuration management using Pydantic Settings.
    Reads from environment variables and .env file.
    """

    # --- Google Cloud ---
    # PROJECT_ID is critical. Support multiple common env var names.
    PROJECT_ID: str = Field(
        validation_alias=AliasChoices("GOOGLE_CLOUD_PROJECT", "GCP_PROJECT_ID"),
        default="super-home-automation",
        description="Google Cloud Project ID",
    )
    REGION: str = Field(validation_alias="GCP_REGION", default="us-central1")
    LOCATION: str = Field(validation_alias="GCP_LOCATION", default="us-central1")
    GCS_BUCKET_NAME: str = Field(validation_alias="GCS_BUCKET_NAME", default="super-home-automation-raw")

    # --- Firestore ---
    FIRESTORE_ORDERS_COLLECTION: str = "orders"
    FIRESTORE_SESSIONS_COLLECTION: str = "sessions"
    SESSION_EXPIRY_HOURS: int = 24

    # --- AI / Gemini ---
    GEMINI_API_KEY: SecretStr | None = Field(validation_alias="GEMINI_API_KEY", default=None)

    # --- Gmail Integration ---
    GMAIL_TOKEN: SecretStr | None = Field(validation_alias="GMAIL_TOKEN", default=None)
    # Comma-separated string of emails to ignore in context
    EXCLUDED_EMAILS_STR: str = Field(validation_alias="EXCLUDED_EMAILS", default="")

    # IDs to ignore (User's company IDs)
    BLACKLIST_IDS_STR: str = Field(validation_alias="BLACKLIST_IDS", default="515020394,029912221")
    # Names to ignore (User's company names)
    BLACKLIST_NAMES_STR: str = Field(validation_alias="BLACKLIST_NAMES", default="סופר הום,שטובה אינטרנשיונל")

    # --- Web UI ---
    WEB_UI_URL: str = Field(validation_alias="WEB_UI_URL", default="http://localhost:8501")

    # --- App Config ---
    LOG_LEVEL: str = Field(validation_alias="LOG_LEVEL", default="INFO")
    ENVIRONMENT: str = Field(validation_alias="ENVIRONMENT", default="dev")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore undefined env vars in .env
    )

    @property
    def excluded_emails(self) -> list[str]:
        """Parsed list of excluded emails, combined with defaults in constants."""
        base_list = constants.EXCLUDED_EMAILS
        if not self.EXCLUDED_EMAILS_STR:
            return base_list
        
        env_list = [e.strip().lower() for e in self.EXCLUDED_EMAILS_STR.split(",") if e.strip()]
        # Union of both lists
        return list(set(base_list + env_list))

    @property
    def blacklist_ids(self) -> set[str]:
        """Set of blacklisted IDs, combined with defaults in constants."""
        base_set = set(constants.BLACKLIST_IDS)
        if not self.BLACKLIST_IDS_STR:
            return base_set
        
        env_set = {id.strip() for id in self.BLACKLIST_IDS_STR.split(",") if id.strip()}
        return base_set.union(env_set)

    @property
    def blacklist_emails(self) -> set[str]:
        """Set of blacklisted emails (Same as excluded_emails, but as a Set)."""
        return set(self.excluded_emails)

    @property
    def blacklist_names(self) -> list[str]:
        """List of blacklisted company names, combined with defaults in constants."""
        base_list = constants.BLACKLIST_NAMES
        if not self.BLACKLIST_NAMES_STR:
            return base_list
        
        env_list = [n.strip() for n in self.BLACKLIST_NAMES_STR.split(",") if n.strip()]
        return list(set(base_list + env_list))


# Singleton instance
settings = Settings()
