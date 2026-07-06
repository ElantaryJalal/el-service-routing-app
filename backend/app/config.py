"""Application settings, loaded from environment / .env."""

from datetime import time

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://el_service:el_service@localhost:5432/el_service"
    )
    # Extraction reader: "local" = on-device Tesseract OCR (offline, no API),
    # "ollama" = free local vision model via an Ollama server (slow on CPU but
    # reads with context, far more accurate than Tesseract on photos),
    # "anthropic" = vision model via the Messages API. The store catalog resolves
    # the read either way, so a cheap/imperfect reader is acceptable when
    # stores are in the catalog.
    extraction_provider: str = "local"
    # Tesseract language(s), e.g. "eng" or "deu+eng" if the German pack is
    # installed (apt-get install tesseract-ocr-deu). eng handles German store
    # names / postal codes fine; deu improves umlauts.
    ocr_languages: str = "eng"
    anthropic_api_key: str = ""
    # Vision model used when extraction_provider="anthropic". Cheap is fine:
    # extraction runs ~weekly per tour and the catalog fills the details.
    extraction_model: str = "claude-haiku-4-5"
    # Ollama server + vision model used when extraction_provider="ollama".
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5vl:3b"
    # CPU inference on a big plan takes minutes; generous by design.
    ollama_timeout_seconds: int = 1800
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    osrm_url: str = "http://localhost:5000"
    vroom_url: str = "http://localhost:3000"
    # Comma-separated CORS origins for browser clients (web build, dashboard).
    # "*" is fine for local dev; set explicit origins in production.
    cors_allow_origins: str = "*"

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


settings = Settings()
