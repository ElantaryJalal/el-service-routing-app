from app.api.auth import router as auth_router
from app.api.feedback import router as feedback_router
from app.api.me import router as me_router
from app.api.stops import router as stops_router
from app.api.stores import router as stores_router
from app.api.tours import router as tours_router
from app.api.users import router as users_router

__all__ = [
    "auth_router",
    "feedback_router",
    "me_router",
    "stops_router",
    "stores_router",
    "tours_router",
    "users_router",
]
