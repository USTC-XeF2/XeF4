from nonebot import require

require("nonebot_plugin_alconna")
require("nonebot_plugin_localstore")

from . import handler

__all__ = ["handler"]
