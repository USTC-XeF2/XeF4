from nonebot import require

require("nonebot_plugin_localstore")
require("nonebot_plugin_group_config")

from .chat import load_models
from . import handler as _

load_models()
