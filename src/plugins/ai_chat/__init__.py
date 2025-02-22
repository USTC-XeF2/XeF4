from nonebot import require

require("nonebot_plugin_localstore")
require("nonebot_plugin_group_config")

from nonebot_plugin_group_config import GroupConfigManager

gcm = GroupConfigManager({
    "response-level": "at",
    "min-corresponding-length": 5,
    "reply-interval": 1.5
}, "chat")

from .chat import load_models
from . import handler as _

load_models()
