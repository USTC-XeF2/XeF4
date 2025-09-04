import asyncio

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    MessageEvent,
    MessageSegment,
)
from nonebot_plugin_alconna import (
    Alconna,
    Args,
    CommandMeta,
    Match,
    Option,
    Subcommand,
    on_alconna,
)

from ..recorder import Recorder
from ..session_config import get_config_path, get_session_config, save_config
from .chat import get_image, get_predict, group_chat
from .config import SConfig
from .tools import ToolReturn
from .utils import convert_messages, format_message, get_name

SessionConfig = get_session_config(SConfig)
uin_range = None


async def should_reply(
    bot: Bot, event: MessageEvent, session_config: SConfig = SessionConfig
):
    global uin_range
    if uin_range is None:
        uin_range = await bot.get_robot_uin_range()
    if any(int(r["minUin"]) <= event.user_id <= int(r["maxUin"]) for r in uin_range):
        logger.info(f"ignore robot message: {event.user_id}")
        return False
    if session_config.chat_response_level == "disabled":
        return False
    return event.is_tome() or not (
        session_config.chat_response_level == "at"
        or len(event.message.extract_plain_text())
        < session_config.chat_min_corresponding_length
    )


chat_command = on_alconna(
    Alconna(
        "chat",
        Subcommand(
            "prompt",
            Option("set", Args["prompt", str], help_text="设置提示词"),
            Option("clear", help_text="清空提示词"),
            help_text="查看提示词",
        ),
        Option("clear", help_text="清空消息记录"),
        meta=CommandMeta(description="机器人聊天控制指令", compact=True),
    ),
    use_cmd_start=True,
    priority=0,
    block=True,
)
group_message = on_message(rule=should_reply, priority=99)


async def set_cutoff(bot: Bot, event: MessageEvent, message: str):
    res = await bot.send(event=event, message=message, reply_message=True)
    recorder = await Recorder.get(bot, event)
    recorder.cutoff = res["message_id"]
    await chat_command.finish()


@chat_command.assign("prompt.set")
async def _(
    bot: Bot,
    event: MessageEvent,
    prompt: Match[str],
    session_config: SConfig = SessionConfig,
):
    session_config.chat_prompt = prompt.result
    save_config(get_config_path(event), session_config)
    await set_cutoff(bot, event, "设置成功")


@chat_command.assign("prompt.clear")
async def _(bot: Bot, event: MessageEvent, session_config: SConfig = SessionConfig):
    session_config.chat_prompt = ""
    save_config(get_config_path(event), session_config)
    await set_cutoff(bot, event, "清空成功")


@chat_command.assign("prompt")
async def _(bot: Bot, event: MessageEvent, session_config: SConfig = SessionConfig):
    text = (
        f"当前提示词：\n{session_config.chat_prompt}"
        if session_config.chat_prompt
        else "当前未设置提示词"
    )
    await set_cutoff(bot, event, text)


@chat_command.assign("clear")
async def _(bot: Bot, event: MessageEvent):
    await set_cutoff(bot, event, "清空成功")


@group_message.handle()
async def _(
    bot: Bot, event: GroupMessageEvent, session_config: SConfig = SessionConfig
):
    recorder = await Recorder.get(bot, event)

    bot_name = await get_name(bot, event.group_id, int(bot.self_id))
    group_info = await bot.get_group_info(group_id=event.group_id)
    history = [
        await format_message(bot, event.group_id, msg, read_file=True)
        for msg in recorder.get_messages(50)
    ]

    chat_coroutine = group_chat(
        bot_name, group_info["group_name"], session_config.chat_prompt, history
    )
    chat_task = asyncio.create_task(chat_coroutine) if event.is_tome() else None

    desire_threshold = 3 if event.is_tome() else 9
    try:
        predict = await get_predict(bot_name, group_info["group_name"], history)
        logger.info(f"desire level: {predict.desire}/{desire_threshold}")
        logger.info(f"reason: {predict.reason}")
    except Exception as e:
        logger.warning(f"get predict failed: {e}")
        predict = None

    if not predict or predict.desire < desire_threshold:
        if event.is_tome():
            await bot.group_poke(group_id=event.group_id, user_id=event.user_id)
        if chat_task:
            chat_task.cancel()
        else:
            chat_coroutine.close()
        return

    messages = []
    try:
        chat_result = await (chat_task if chat_task else chat_coroutine)
        if isinstance(chat_result, ToolReturn):
            if chat_result.type == "image":
                try:
                    image = await get_image(prompt=chat_result.result)
                except Exception as e:
                    logger.error(f"generate image failed: {e}")
                    image = None
                if image:
                    messages.append(MessageSegment.image(image))
                else:
                    messages.append("图片生成失败")
        else:
            name_map = {
                m.sender_name: m.sender.user_id
                for m in recorder.msg_history
                if m.sender_name and m.sender.user_id
            }
            messages.extend(convert_messages(chat_result, name_map))
    except Exception as e:
        logger.error(f"get chat result failed: {e}")

    if len(messages) == 0:
        await bot.group_poke(group_id=event.group_id, user_id=event.user_id)
        return
    await group_message.send(messages[0], reply_message=True)
    for msg in messages[1:]:
        await asyncio.sleep(1.5)
        await group_message.send(msg)
