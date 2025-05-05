import time
import random
import asyncio

from nonebot import logger, on_message, on_type
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupIncreaseNoticeEvent,
    GroupMessageEvent,
    MessageSegment,
    PokeNotifyEvent
)
from nonebot_plugin_group_config import (
    GroupConfig as GC,
    GroupConfigManager,
    GetGroupConfig as GetGC
)

from .recorder import Recorder

gcm = GroupConfigManager({
    "poke-delay": 0.5,
    "welcome-emoji-id": -1,
    "plus-one-delay": 1.5
})

async def plus_one_filter(bot: Bot, event: GroupMessageEvent):
    recorder = await Recorder.get(event.group_id, bot)
    return recorder.msg_repeat_count > 1

poke_handler = on_type(PokeNotifyEvent)
welcome_handler = on_type(GroupIncreaseNoticeEvent)
plus_one_handler = on_message(rule=plus_one_filter)

@poke_handler.handle()
async def _(bot: Bot, event: PokeNotifyEvent, group_config: GC = GetGC(gcm)):
    special = bot.config.superusers | {bot.self_id} 
    if str(event.user_id) not in special and str(event.target_id) in special:
        logger.info(f"poke back: {event.user_id}")
        await asyncio.sleep(group_config["poke-delay"])
        await bot.call_api("group_poke", group_id=event.group_id, user_id=event.user_id)

@welcome_handler.handle()
async def _(bot: Bot, group_config: GC = GetGC(gcm)):
    if (emoji_id := group_config["welcome-emoji-id"]) != -1:
        emojis = await bot.call_api("fetch_custom_face")
        await welcome_handler.finish(MessageSegment("image", {
            "file": emojis[emoji_id],
            "sub_type": 1
        }))

last_repeat: dict[int, tuple[str, int]] = {}

@plus_one_handler.handle()
async def _(bot: Bot, event: GroupMessageEvent, group_config: GC = GetGC(gcm)):
    recorder = await Recorder.get(event.group_id, bot)
    count = recorder.msg_repeat_count
    if any(str(e.user_id) == bot.self_id for e in recorder.msg_history[-1:-count-1:-1]):
        return
    rep_msg, rep_times = last_repeat.get(event.group_id, ("", 0))
    last_msg = recorder.last_msg
    if rep_msg == last_msg and time.time() - rep_times < group_config["plus-one-delay"] * 2:
        return
    if random.random() < (count-1)/(count+1):
        last_repeat[event.group_id] = (last_msg, time.time())
        logger.info(f"plus one after {count} repeat: {last_msg}")
        await asyncio.sleep(group_config["plus-one-delay"])
        await plus_one_handler.finish(event.original_message)
