import asyncio

from nonebot import logger, on_command, on_message
from nonebot.permission import SUPERUSER
from nonebot.params import Command, CommandArg
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot_plugin_group_config import GroupConfig, GroupConfigManager, GetGroupConfig

from ..recorder import Recorder

from .utils import get_name, image_storage, generate_message, get_dumped_messages, get_image_data, get_file_segment
from .chat import load_models, get_preprocess_info, get_image_description, search, generate_image, chat

gcm = GroupConfigManager({
    "response-level": "at",
    "min-corresponding-length": 8,
    "max-history-length": 30,
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

chat_cmd = on_command(
    "chat",
    aliases={
        ("chat", "clear"),
        ("chat", "prompt"),
        ("chat", "prompt", "clear")
    },
    force_whitespace=True,
    priority=0,
    block=True
)
reload_cmd = on_command(
    ("chat", "reload"),
    force_whitespace=True,
    permission=SUPERUSER,
    priority=0,
    block=True
)
message_handler = on_message(rule=_check_is_enable, priority=99)

last_clear_msg = dict[int, int]()

@chat_cmd.handle()
async def _(
    event: GroupMessageEvent,
    cmd: tuple[str, ...] = Command(),
    args: Message = CommandArg(),
    group_config: GroupConfig = GetGroupConfig(gcm)
):
    if cmd == ("chat",):
        text = """/chat.clear: 清空消息记录
/chat.prompt: 查看或设置提示词
/chat.prompt.clear: 清空提示词
/chat.reload: 重新加载模型（仅限管理员使用）"""
    else:
        last_clear_msg[event.group_id] = event.message_id
        if cmd == ("chat", "clear"):
            text = "清空成功"
        elif cmd == ("chat", "prompt"):
            ipt = args.extract_plain_text().strip()
            if not ipt:
                text = f"当前群聊提示词：\n{group_config['prompt']}"
            else:
                group_config["prompt"] = ipt
                text = "设置成功"
        else:
            group_config["prompt"] = ""
            text = "清空成功"
    await chat_cmd.finish(text, reply_message=True)

@reload_cmd.handle()
async def _():
    try:
        load_models()
    except Exception as e:
        await reload_cmd.finish(f"重新加载模型失败: {e.args[0]}", reply_message=True)
    await reload_cmd.finish("重新加载模型成功", reply_message=True)

uin_range: list[dict[str, str]] = None

@message_handler.handle()
async def _(bot: Bot, event: GroupMessageEvent, group_config: GroupConfig = GetGroupConfig(gcm)):
    global uin_range
    if uin_range is None:
        uin_range = await bot.get_robot_uin_range()
    if any(int(r["minUin"]) <= event.user_id <= int(r["maxUin"]) for r in uin_range):
        logger.info(f"ignore robot message: {event.user_id}")
        return
    recorder = await Recorder.get(event.group_id, bot)
    image_storage.clear()
    new_messages = list[str]()
    e = event
    while e:
        new_messages.append(await generate_message(bot, e, try_read_file=True))
        e = recorder.get_reply_msg(e)
    history_messages = list[str]()
    for e in recorder.msg_history[::-1]:
        if e == event:
            continue
        if e.message_id == last_clear_msg.get(event.group_id):
            break
        if len(history_messages) >= group_config["max-history-length"]:
            break
        history_messages.insert(0, await generate_message(bot, e))
    logger.info(f"current history length: {len(history_messages)}")

    dumped_messages = get_dumped_messages(
        await bot.get_group_info(group_id=event.group_id),
        await get_name(bot, event.group_id, bot.self_id),
        history_messages, new_messages
    )
    preprocess_info = await get_preprocess_info(dumped_messages)
    if not preprocess_info:
        logger.warning("get preprocess info failed")
        return
    desire_threshold = 6 if event.is_tome() else 17

    if preprocess_info["search"]:
        desire_threshold -= 1
        logger.info(f"search: {preprocess_info['search']}")
    logger.info(f"desire level: {preprocess_info['desire']}/{desire_threshold}")
    logger.info(f"reason: {preprocess_info['reason']}")
    if preprocess_info["desire"] < desire_threshold or not recorder.get_msg(event.message_id):
        if event.is_tome():
            await bot.group_poke(group_id=event.group_id, user_id=event.user_id)
        return

    image_desc = []
    for id, prompt in preprocess_info["images"].items():
        try:
            image_data = get_image_data(image_storage[id])
            if not image_data:
                continue
            description = await get_image_description(image_data, prompt)
            if description:
                image_desc.append((id, description))
                logger.info(f"image {id}: {prompt!r}")
        except Exception:
            continue
    search_info = [res for res in await asyncio.gather(
        *map(search, preprocess_info["search"])
    ) if res]
    think = preprocess_info["think"]
    if think:
        await bot.send(event, "🤔", reply_message=True)
    response = []
    for msg in await chat(dumped_messages, group_config["prompt"], image_desc, search_info, think):
        if isinstance(msg, str):
            type = "text"
            content = msg
        else:
            type = msg["type"]
            content = msg["content"]

        if type == "text":
            logger.info(f"text: {content}")
            response.append(content)
        elif type == "image":
            logger.info(f"image: {content}")
            url = await generate_image(content)
            if url:
                response.append(MessageSegment.image(url))
        elif type == "file":
            logger.info(f"file: {msg['filename']}")
            response.append(get_file_segment(msg["filename"], content.encode()))
    response = [msg for msg in response if msg]

    if not (response and recorder.get_msg(event.message_id)):
        await bot.group_poke(group_id=event.group_id, user_id=event.user_id)
        return
    interval = group_config["reply-interval"]
    await bot.send(event, response[0], reply_message=isinstance(response[0], str))
    for msg in response[1:]:
        await asyncio.sleep(interval)
        await bot.send(event, msg)
