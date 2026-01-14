from pathlib import Path
from typing import TypeVar

import yaml
from nonebot import require
from nonebot.params import Depends
from nonebot.rule import Rule
from pydantic import BaseModel

from .interceptor import RecordedEvent
from .recorder import parse_session

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


def get_session_config(config_type: type[T]):
    def get_config(event: RecordedEvent):
        session_id = parse_session(event)[0]
        config_path = get_session_config_dir(event.self_id) / f"{session_id}.yaml"
        return load_config(config_path, config_type)

    return Depends(get_config)


def check_enable(config_type: type[T], key: str):
    def checker(session_config: T = get_session_config(config_type)):
        return getattr(session_config, key)

    return Rule(checker)
