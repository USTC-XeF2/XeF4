import asyncio
import random
import time

from nonebot import get_plugin_config, logger, on_message, on_type
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PokeNotifyEvent
from pydantic import BaseModel

from .recorder import Recorder


class Config(BaseModel):
    poke_delay: float = 0.5
    poke_cooldown: float = 5.0
    plus_one_delay: float = 1.0
    plus_one_cooldown: float = 3.0


config = get_plugin_config(Config)


async def plus_one_filter(bot: Bot, event: GroupMessageEvent):
    recorder = await Recorder.get(bot, event)
    return (
        len(recorder.msg_repeat_users) > 1
        and int(bot.self_id) not in recorder.msg_repeat_users
    )


poke_handler = on_type(PokeNotifyEvent)
plus_one_handler = on_message(rule=plus_one_filter)


last_poke: dict[int, float] = {}


@poke_handler.handle()
async def _(bot: Bot, event: PokeNotifyEvent):
    special = bot.config.superusers | {bot.self_id}
    if str(event.user_id) not in special and str(event.target_id) in special:
        await asyncio.sleep(config.poke_delay)
        if time.time() - last_poke.get(event.user_id, 0) < config.poke_cooldown:
            return
        await bot.group_poke(group_id=event.group_id, user_id=event.user_id)
        last_poke[event.user_id] = time.time()


last_repeat: dict[int, tuple[str, float]] = {}


@plus_one_handler.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    recorder = await Recorder.get(bot, event)
    rep_msg, rep_time = last_repeat.get(event.group_id, ("", 0))
    last_msg = recorder.last_msg
    if rep_msg == last_msg or time.time() - rep_time < config.plus_one_cooldown:
        return

    count = len(recorder.msg_repeat_users)
    if random.random() < (count - 1) / (count + 1):
        last_repeat[event.group_id] = (last_msg or "", time.time())
        logger.info(f"plus one after {count} repeat: {last_msg}")
        await asyncio.sleep(config.plus_one_delay)
        await plus_one_handler.finish(event.original_message)
