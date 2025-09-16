import re
from datetime import datetime

from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment

from ..recorder import RecordMessage


async def get_name(bot: Bot, group_id: int, user_id: int) -> str:
    info = await bot.get_group_member_info(group_id=group_id, user_id=user_id)
    return info["card"] or info["nickname"]


async def format_message(
    bot: Bot, group_id: int, message: RecordMessage, read_file: bool
):
    format_time = datetime.fromtimestamp(message.time).strftime("%H:%M:%S")
    role_prefix = (
        "<admin>"
        if message.sender.role == "admin"
        else "<owner>"
        if message.sender.role == "owner"
        else ""
    )
    sender_name = (message.sender_name or "").replace("<", "").replace(">", "")
    refer = ""
    content = ""
    for msg_seg in message.message:
        if msg_seg.type == "text":
            content += msg_seg.data["text"]
        elif msg_seg.type == "reply":
            reply_msg = await bot.get_msg(message_id=msg_seg.data["id"])
            reply_msg["post_type"] = "message"
            reply_event = MessageEvent(**reply_msg)
            text = reply_event.original_message.extract_plain_text().strip()
            refer = f"/ref/ {(text[:20] + '...' if len(text) > 20 else text)!r}\n"
        elif msg_seg.type == "at":
            user_id: str = msg_seg.data["qq"]
            if user_id.isdigit():
                content += "@" + await get_name(bot, group_id, int(user_id))
            else:
                content += "@全体成员"
        elif msg_seg.type == "image":
            if msg_seg.data["summary"]:
                content += msg_seg.data["summary"]
            else:
                content += "[图片:]"
        elif msg_seg.type == "file":
            if read_file and int(msg_seg.data["file_size"]) <= 4096:
                file = (await bot.get_file(file_id=msg_seg.data["file_id"]))["file"]
                try:
                    with open(file) as rf:
                        content = rf.read()
                    break
                except (OSError, ValueError):
                    pass
            name = msg_seg.data["file"]
            content += f"[文件:{name}]"
    return f"[{format_time} {role_prefix}{sender_name}]\n{refer}{content}"


def convert_messages(
    messages: list[str],
    name_map: dict[str, int],
    max_count: int = 8,
    max_length: int = 500,
):
    sorted_names = sorted(name_map.keys(), key=lambda x: -len(x))
    at_pattern = re.compile("@(" + "|".join(map(re.escape, sorted_names)) + r")")

    converted_messages: list[Message] = []
    for msg in messages:
        if len(msg) > max_length:
            msg = msg[:max_length].rstrip()

        last_idx = 0
        segs = []
        for match in at_pattern.finditer(msg):
            start, end = match.span()
            name = match.group(1)
            if start > last_idx:
                segs.append(MessageSegment.text(msg[last_idx:start]))
            segs.append(MessageSegment.at(name_map[name]))
            last_idx = end
        if last_idx < len(msg):
            segs.append(MessageSegment.text(msg[last_idx:]))
        if segs:
            converted_messages.append(Message(segs))
            if len(converted_messages) >= max_count:
                break

    return converted_messages
