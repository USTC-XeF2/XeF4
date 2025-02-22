import time
import json
import base64

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment

async def get_name(bot: Bot, group_id: int, user_id: int) -> str:
    info = await bot.get_group_member_info(group_id=group_id, user_id=user_id)
    return info["card"] or info["nickname"]

async def generate_message(bot: Bot, event: GroupMessageEvent) -> str:
    format_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(event.time))
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
            content += msg_seg.data["summary"] or "[图片]"
    return f"[{format_time} {sender_name}]\n{content}"

def get_dumped_messages(name: str, history_messages: list[str], new_messages: list[str]):
    return [{
        "role": "user",
        "content": i
    } for i in (
        f"你的名字是{name}",
        f"历史消息：{json.dumps(history_messages, ensure_ascii=False)}",
        f"新消息及引用消息链：{json.dumps(new_messages, ensure_ascii=False)}"
    )]

def get_file_segment(filename: str, content: bytes):
    b64file = base64.b64encode(content).decode()
    return MessageSegment("file", {
        "name": filename,
        "file": f"base64://{b64file}"
    })
