"""Application settings, loaded from environment / .env."""

from datetime import time

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://el_service:el_service@localhost:5432/el_service"
    )
    anthropic_api_key: str = ""
    extraction_model: str = "claude-sonnet-5"
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    osrm_url: str = "http://localhost:5000"
    vroom_url: str = "http://localhost:3000"

    # --- Optimiser inputs ---
    working_day_start: time = time(7, 0)
    working_day_end: time = time(19, 0)
    default_service_minutes: int = 60
    # Weekday indices to skip (Mon=0 .. Sun=6). Default skips Sunday.
    skip_weekdays: str = "6"
    # A day counts as "near its limit" if it ends within this many minutes of
    # the working-day end.
    near_limit_minutes: int = 30

    @property
    def skip_weekday_set(self) -> set[int]:
        return {int(x) for x in self.skip_weekdays.split(",") if x.strip() != ""}


settings = Settings()
