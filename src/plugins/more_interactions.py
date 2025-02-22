import random
import asyncio

from nonebot import logger, on_message, on_type
from nonebot.matcher import Matcher
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

poke_handler = on_type(PokeNotifyEvent)
welcome_handler = on_type(GroupIncreaseNoticeEvent)
plus_one_handler = on_message(block=False)

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

@plus_one_handler.handle()
async def _(bot: Bot, matcher: Matcher, event: GroupMessageEvent, group_config: GC = GetGC(gcm)):
    recorder = await Recorder.get(event.group_id, bot)
    count = 0
    last_msg = None
    for e in recorder.msg_history[::-1]:
        if str(e.user_id) == bot.self_id:
            return
        msg = e.original_message.to_rich_text()
        if not count:
            last_msg = msg
            count += 1
        elif msg == last_msg:
            matcher.stop_propagation()
            count += 1
        else:
            break
    if random.random() < (count-1)/(count+1):
        logger.info(f"plus one after {count} repeat: {last_msg}")
        await asyncio.sleep(group_config["plus-one-delay"])
        await plus_one_handler.finish(event.original_message)
