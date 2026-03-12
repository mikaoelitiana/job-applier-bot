from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM — change this one variable to switch providers
    # Examples:
    #   anthropic/claude-sonnet-4-6
    #   openai/gpt-4o
    #   gemini/gemini-2.0-flash
    #   ollama/llama3
    #   perplexity/sonar-pro
    #   openrouter/google/gemini-2.0-flash-exp
    llm_model: str = Field(default="anthropic/claude-sonnet-4-6", alias="LLM_MODEL")

    # Anthropic
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")

    # OpenAI (optional alternative provider)
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")

    # Google Gemini (optional alternative provider)
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")

    # Perplexity (optional alternative provider, OpenAI-compatible)
    perplexity_api_key: str | None = Field(default=None, alias="PERPLEXITY_API_KEY")

    # OpenRouter (optional alternative provider, OpenAI-compatible)
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")

    # Telegram
    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")

    # Optional: restrict bot to specific Telegram user IDs (comma-separated)
    # Leave empty to allow any user
    allowed_telegram_user_ids: str = Field(default="", alias="ALLOWED_TELEGRAM_USER_IDS")

    # Google Sheets
    # Provide either the raw JSON content or a path to the file
    google_service_account_json: str | None = Field(default=None, alias="GOOGLE_SERVICE_ACCOUNT_JSON")
    google_service_account_file: str = Field(
        default="assets/service_account.json",
        alias="GOOGLE_SERVICE_ACCOUNT_FILE",
    )
    google_sheet_id: str = Field(alias="GOOGLE_SHEET_ID")
    google_sheet_tab: str = Field(default="Applications", alias="GOOGLE_SHEET_TAB")

    # Assets
    resume_path: str = Field(default="assets/resume.pdf", alias="RESUME_PATH")
    profile_path: str = Field(default="assets/profile.json", alias="PROFILE_PATH")

    # Log file — written inside the assets volume so logs survive container restarts
    log_file: str = Field(default="/app/assets/applier.log", alias="LOG_FILE")

    @property
    def allowed_user_ids(self) -> list[int]:
        if not self.allowed_telegram_user_ids.strip():
            return []
        return [int(uid.strip()) for uid in self.allowed_telegram_user_ids.split(",") if uid.strip()]


settings = Settings()
