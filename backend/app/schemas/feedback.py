from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.visit_feedback import FeedbackTag


class FeedbackCreate(BaseModel):
    """One piece of after-visit feedback. store_id/tour_id are derived from
    the stop server-side so the row can't contradict itself. client_uuid is
    the client-generated idempotency key: offline sync may retry the same
    POST, which must return the existing row instead of creating another."""

    stop_id: int
    client_uuid: str
    employee: str | None = None
    tags: list[FeedbackTag] = []
    note: str | None = None
    photo_path: str | None = None


class PhotoUploadResult(BaseModel):
    """Where an uploaded feedback photo landed; served under /media."""

    photo_path: str


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: int | None
    # Display identity — feedback is shown to people, never as a raw store id.
    store_name: str | None
    store_city: str | None
    tour_id: int | None
    stop_id: int | None
    employee: str | None
    is_demo: bool
    tags: list[str]
    note: str | None
    photo_path: str | None
    client_uuid: str
    created_at: datetime
