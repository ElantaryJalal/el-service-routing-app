"""Application settings, loaded from environment / .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://el_service:el_service@localhost:5432/el_service"
    )
    anthropic_api_key: str = ""
    extraction_model: str = "claude-sonnet-5"
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    osrm_url: str = "http://localhost:5000"
    vroom_url: str = "http://localhost:3000"


settings = Settings()
