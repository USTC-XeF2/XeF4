from pathlib import Path
from typing import TypeVar

import yaml
from nonebot import require
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.params import Depends
from pydantic import BaseModel

require("nonebot_plugin_localstore")

from nonebot_plugin_localstore import get_config_dir

T = TypeVar("T", bound=BaseModel)


def get_session_config_dir(bot_id: str | int):
    return get_config_dir(f"session-{bot_id}")


def load_config(config_path: Path, config_type: type[T]):
    config_path.touch()
    with config_path.open(encoding="utf-8") as rf:
        data = yaml.safe_load(rf)
    if data:
        return config_type.model_validate(data)
    return config_type()


def save_config(config_path: Path, config: BaseModel):
    config_path.touch()
    with config_path.open(encoding="utf-8") as rf:
        data = yaml.safe_load(rf) or {}
    with config_path.open("w", encoding="utf-8") as wf:
        yaml.safe_dump(data | config.model_dump(), wf, allow_unicode=True)


def get_config_path(event: MessageEvent):
    session_id = (
        event.group_id if isinstance(event, GroupMessageEvent) else event.user_id
    )
    return (
        get_session_config_dir(event.self_id)
        / f"{event.message_type}-{session_id}.yaml"
    )


def get_session_config(config_type: type[T]):
    def get_config(event: MessageEvent):
        return load_config(get_config_path(event), config_type)

    return Depends(get_config)
