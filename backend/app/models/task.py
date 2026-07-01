from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    stop_id: Mapped[int] = mapped_column(
        ForeignKey("stops.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # e.g. EKW, KORBE_SAMMELSTATION, GASKUEHLER, FUSSMATTEN
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    raw_label: Mapped[str | None] = mapped_column(String)

    stop: Mapped["Stop"] = relationship(back_populates="tasks")  # noqa: F821
