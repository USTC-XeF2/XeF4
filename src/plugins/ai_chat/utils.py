import time
import json
import base64
import random
import requests

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment

TIMEZONE = 28800  # UTC+8

async def get_name(bot: Bot, group_id: int, user_id: int) -> str:
    info = await bot.get_group_member_info(group_id=group_id, user_id=user_id)
    return info["card"] or info["nickname"]

image_storage = dict[str, str]()

async def generate_message(bot: Bot, event: GroupMessageEvent, try_read_file: bool = False) -> str:
    format_time = time.strftime("%H:%M:%S", time.gmtime(event.time + TIMEZONE))
    sender_name = event.sender.card or event.sender.nickname
    content = ""
    for msg_seg in event.original_message:
        if msg_seg.type == "text":
            content += msg_seg.data["text"]
        elif msg_seg.type == "at":
            user_id: str = msg_seg.data["qq"]
            if user_id.isdigit():
                content += "@" + await get_name(bot, event.group_id, user_id)
            else:
                content += "@全体成员"
        elif msg_seg.type == "image":
            if msg_seg.data["summary"]:
                content += msg_seg.data["summary"]
            else:
                id = next(
                    (k for k, v in image_storage.items() if v == msg_seg.data["url"]),
                    str(random.randint(100000, 999999))
                )
                content += f"[图片-{id}]"
                image_storage[id] = msg_seg.data["url"]
        elif msg_seg.type == "file":
            if try_read_file and int(msg_seg.data["file_size"]) <= 4096:
                file = (await bot.get_file(file_id=msg_seg.data["file_id"]))["file"]
                try:
                    with open(file) as rf:
                        content = rf.read()
                    break
                except (OSError, ValueError):
                    pass
            name = msg_seg.data["file"]
            content += f"[文件-{name}]"
    role_prefix = "{管理员}" if event.sender.role == "admin" else ""
    return f"{role_prefix}[{format_time} {sender_name}]\n{content}"

def get_dumped_messages(group_info: dict[str], name: str, history_messages: list[str], new_messages: list[str]):
    return [{
        "role": "user",
        "content": i
    } for i in (
        f"你的名字是{name}",
        f"群聊名称：{group_info['group_name']} ({group_info['member_count']}人)",
        f"历史消息：{json.dumps(history_messages, ensure_ascii=False)}",
        f"新消息及引用消息链：{json.dumps(new_messages, ensure_ascii=False)}"
    )]

def get_image_data(url: str):
    res = requests.get(url)
    if res.status_code != 200:
        return
    content_type = res.headers["Content-Type"]
    if not content_type.startswith("image/"):
        return
    b64 = base64.b64encode(res.content).decode()
    return f"data:{content_type};base64,{b64}"

def get_file_segment(filename: str, content: bytes):
    b64file = base64.b64encode(content).decode()
    return MessageSegment("file", {
        "name": filename,
        "file": f"base64://{b64file}"
    })
