"""Push-token registration payloads."""

from typing import Literal

from pydantic import BaseModel, Field


class PushTokenRegister(BaseModel):
    """POST /me/push-tokens body: this device's Expo push token."""

    token: str = Field(min_length=1, max_length=400)
    platform: Literal["ios", "android"] | None = None
