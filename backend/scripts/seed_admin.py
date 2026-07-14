"""Seed the initial admin user from ADMIN_EMAIL / ADMIN_PASSWORD.

Idempotent: if a user with that email already exists, it is promoted to an
active admin but its password is NOT overwritten. Prints what happened.

    cd backend
    ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=changeme \
      python -m scripts.seed_admin
"""

import sys

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models.user import Role, User
from app.security import hash_password


def main() -> None:
    email = settings.admin_email.strip().lower()
    if not email or not settings.admin_password:
        sys.exit("Set ADMIN_EMAIL and ADMIN_PASSWORD (env or .env) first.")

    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is not None:
            user.role = Role.admin
            user.is_active = True
            db.commit()
            print(f"user {email} already exists (id={user.id}); ensured active admin")
            return

        user = User(
            email=email,
            password_hash=hash_password(settings.admin_password),
            name="Admin",
            role=Role.admin,
        )
        db.add(user)
        db.commit()
        print(f"created admin {email} (id={user.id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
