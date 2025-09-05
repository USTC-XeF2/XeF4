from typing import Literal

from pydantic import BaseModel, SecretStr


class Config(BaseModel):
    chat_api_key: SecretStr
    chat_base_url: str
    chat_model: str
    thinking_model: str | None = None
    image_api_key: str | None = None
    image_model: str = "core"


class SConfig(BaseModel):
    chat_response_level: Literal["disabled", "at", "all"] = "at"
    chat_min_corresponding_length: int = 5
    chat_max_history_length: int = 50
