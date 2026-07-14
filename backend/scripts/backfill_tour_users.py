"""Backfill tours.assigned_user_id from the free-text tours.employee names.

For each distinct non-empty employee name on tours without an assigned user,
find or create a role='worker' User (email `<slug>@imported.elservice.de`, unusable
password hash — they cannot log in until an admin sets a real password) and
link the tours to it. Idempotent: reruns match the existing imported users and
skip already-linked tours.

    cd backend
    python -m scripts.backfill_tour_users
"""

import re
import unicodedata

from sqlalchemy import select

from app.db import SessionLocal
from app.models.tour import Tour
from app.models.user import Role, User
from app.security import make_unusable_password_hash

# Must be a syntactically real domain: the API's EmailStr validation rejects
# special-use TLDs like .local, which would make these accounts unmanageable.
IMPORT_DOMAIN = "imported.elservice.de"


def _slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug or "worker"


def _find_or_create_worker(db, name: str) -> tuple[User, bool]:
    """Return (user, created) for an imported worker name."""
    base_slug = _slugify(name)
    slug = base_slug
    suffix = 2
    while True:
        email = f"{slug}@{IMPORT_DOMAIN}"
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            user = User(
                email=email,
                password_hash=make_unusable_password_hash(),
                name=name,
                role=Role.worker,
            )
            db.add(user)
            db.flush()
            return user, True
        if user.name == name:
            return user, False
        # Same slug, different person (e.g. "Ali B." vs "Ali B"): disambiguate.
        slug = f"{base_slug}-{suffix}"
        suffix += 1


def main() -> None:
    db = SessionLocal()
    try:
        tours = (
            db.execute(
                select(Tour).where(
                    Tour.assigned_user_id.is_(None),
                    Tour.employee.is_not(None),
                )
            )
            .scalars()
            .all()
        )

        created = 0
        linked = 0
        for tour in tours:
            name = (tour.employee or "").strip()
            if not name:
                continue
            user, was_created = _find_or_create_worker(db, name)
            created += was_created
            tour.assigned_user_id = user.id
            linked += 1

        db.commit()
        skipped = db.execute(
            select(Tour.id).where(Tour.assigned_user_id.is_not(None))
        ).all()
        print(
            f"created {created} users, linked {linked} tours, "
            f"{len(skipped)} tours have an assigned user in total"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
