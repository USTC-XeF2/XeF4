import json
from pathlib import Path

from nonebot import require
from nonebot.adapters.onebot.v11 import MessageEvent, NoticeEvent
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor

require("nonebot_plugin_localstore")

from nonebot_plugin_localstore import get_config_file

RecordedEvent = MessageEvent | NoticeEvent


def parse_session(data: RecordedEvent | dict) -> tuple[int, bool]:
    if not isinstance(data, dict):
        data = data.model_dump()
    is_group = data.get("group_id") is not None
    return data["group_id"] if is_group else data["user_id"], is_group


def read_or_create(path: Path) -> list[int]:
    if not path.exists():
        path.write_text("[]")
        return []
    return json.loads(path.read_text())


enabled_users = read_or_create(get_config_file("global", "enabled-users.json"))
enabled_groups = read_or_create(get_config_file("global", "enabled-groups.json"))


@event_preprocessor
def check_enabled(event: MessageEvent | NoticeEvent):
    s_id, is_group = parse_session(event)
    if s_id not in (enabled_groups if is_group else enabled_users):
        raise IgnoredException("session not enabled")
