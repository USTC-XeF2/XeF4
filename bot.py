import nonebot
from nonebot.message import event_preprocessor
from nonebot.exception import IgnoredException
from nonebot.adapters.onebot.v11 import Adapter as OneBotAdapter, Event
from nonebot.adapters.minecraft import Adapter as MinecraftAdapter

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(OneBotAdapter)
driver.register_adapter(MinecraftAdapter)

@event_preprocessor
def is_enabled_group(event: Event):
    if not hasattr(event, "group_id"):
        return
    config = driver.config
    if config.whitelist_mode ^ (event.group_id in config.namelist):
        raise IgnoredException("group not enabled")

nonebot.load_from_toml("pyproject.toml")

from src.plugins.command import Command
from src.commands import poke, server_info

Command("poke", poke, max_usage_times=5)
Command("server-info", server_info, {"s"})

if __name__ == "__main__":
    nonebot.run()
