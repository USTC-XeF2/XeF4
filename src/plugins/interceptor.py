import json
from pathlib import Path

from nonebot import require
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor

require("nonebot_plugin_localstore")

from nonebot_plugin_localstore import get_config_file


def read_or_create(path: Path) -> list[int]:
    if not path.exists():
        path.write_text("[]")
        return []
    return json.loads(path.read_text())


enabled_users = read_or_create(get_config_file("global", "enabled-users.json"))
enabled_groups = read_or_create(get_config_file("global", "enabled-groups.json"))


@event_preprocessor
def check_private(event: PrivateMessageEvent):
    if event.user_id not in enabled_users:
        raise IgnoredException("user not enabled")


@event_preprocessor
def check_group(event: GroupMessageEvent):
    if event.group_id not in enabled_groups:
        raise IgnoredException("group not enabled")
