import asyncio

from nonebot import logger, on_command, on_message
from nonebot.permission import SUPERUSER
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot_plugin_group_config import GroupConfig, GroupConfigManager, GetGroupConfig

from ..recorder import Recorder

from .utils import get_name, generate_message, get_dumped_messages, get_file_segment
from .chat import load_models, get_preprocess_info, search, chat

import_libs = {
    "re": __import__("re"),
    "math": __import__("math"),
    "random": __import__("random"),
    "time": __import__("time"),
    "datetime": __import__("datetime")
}

gcm = GroupConfigManager({
    "response-level": "at",
    "min-corresponding-length": 5,
    "keywords": "",
    "prompt": "",
    "reply-interval": 1.5
}, "chat")

def _check_is_enable(event: GroupMessageEvent, group_config: GroupConfig = GetGroupConfig(gcm)):
    if group_config["response-level"] == "disabled":
        return False
    return event.is_tome() or not (
        group_config["response-level"] == "at" or
        len(event.message.extract_plain_text()) < group_config["min-corresponding-length"]
    )

reload_cmd = on_command(
    ("chat", "reload"),
    permission=SUPERUSER,
    priority=0,
    block=True
)
prompt_cmd = on_command(
    ("chat", "prompt"),
    priority=0,
    block=True
)
message_handler = on_message(rule=_check_is_enable, priority=99)

@reload_cmd.handle()
async def _():
    try:
        load_models()
    except Exception as e:
        await reload_cmd.finish(f"重新加载模型失败: {e.args[0]}", reply_message=True)
    await reload_cmd.finish("重新加载模型成功", reply_message=True)

@prompt_cmd.handle()
async def _(args: Message = CommandArg(), group_config: GroupConfig = GetGroupConfig(gcm)):
    text = args.extract_plain_text().strip()
    if not text:
        await prompt_cmd.finish(f"当前群聊提示词：\n{group_config['prompt']}", reply_message=True)
    group_config["prompt"] = text
    await prompt_cmd.finish("设置成功", reply_message=True)

@message_handler.handle()
async def _(bot: Bot, event: GroupMessageEvent, group_config: GroupConfig = GetGroupConfig(gcm)):
    recorder = await Recorder.get(event.group_id, bot)
    new_messages = list[str]()
    e = event
    while e:
        new_messages.append(await generate_message(bot, e))
        e = recorder.get_reply_msg(e)

    dumped_messages = get_dumped_messages(
        await get_name(bot, event.group_id, bot.self_id),
        [await generate_message(bot, e) for e in recorder.msg_history if e != event],
        new_messages
    )
    keywords = group_config["keywords"].split(",")
    preprocess_info = await get_preprocess_info(dumped_messages, keywords)
    desire_threshold = 12 if event.is_tome() else 18
    if keywords: desire_threshold += 1
    
    if preprocess_info["search"]:
        desire_threshold -= 2
        logger.info(f"search: {preprocess_info['search']}")
    if preprocess_info["keywords"]:
        desire_threshold -= 3
        logger.info(f"keywords: {preprocess_info['keywords']}/{len(keywords)}")
    logger.info(f"desire level: {preprocess_info['desire']}/{desire_threshold}")
    logger.info(f"reason: {preprocess_info['reason']}")
    if preprocess_info["desire"] < desire_threshold:
        return

    search_info = [res for res in await asyncio.gather(
        *map(search, preprocess_info["search"])
    ) if res]
    response = []
    for msg in await chat(dumped_messages, group_config["prompt"], search_info):
        if isinstance(msg, str):
            type = "text"
            content = msg
        else:
            type = msg["type"]
            content = msg["content"]

        if type == "text":
            logger.info(f"text: {content}")
            response.append(content)
        elif type == "file":
            logger.info(f"file: {msg['filename']}")
            response.append(get_file_segment(msg["filename"], content.encode()))
        elif type == "fstring":
            try:
                formatted_msg = eval(f'f"""{content}"""', import_libs)
                logger.info(f"fstring: {content} -> {formatted_msg}")
                response.append(formatted_msg)
            except Exception as e:
                logger.error(f"failed to format fstring {msg!r}: {e.args}")

    interval = group_config["reply-interval"]
    await bot.send(event, response[0], reply_message=isinstance(response[0], str))
    for msg in response[1:]:
        await asyncio.sleep(interval)
        await bot.send(event, msg)
