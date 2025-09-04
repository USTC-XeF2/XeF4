from __future__ import annotations

import json
from dataclasses import dataclass

from nonebot import get_plugin_config, logger, require
from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    FriendRecallNoticeEvent,
    GroupRecallNoticeEvent,
    Message,
    MessageEvent,
)
from nonebot.adapters.onebot.v11.event import Sender
from nonebot.message import event_preprocessor
from pydantic import BaseModel

require("nonebot_plugin_localstore")

from nonebot_plugin_localstore import get_plugin_data_file


class Config(BaseModel):
    recorder_init_history_length: int = 100
    recorder_max_history_length: int = 1000


config = get_plugin_config(Config)


@dataclass
class RecordMessage:
    id: int
    time: int
    sender: Sender
    message: Message

    @property
    def sender_name(self):
        return self.sender.card or self.sender.nickname


class Recorder:
    _recorders: dict[tuple[str, str], Recorder] = {}

    def __init__(self, bot_id: str, session_id: str):
        self.bot_id = bot_id
        self.session_id = session_id
        self.msg_history: list[RecordMessage] = []
        self.last_msg: str | None = None
        self.msg_repeat_users: set[int] = set()

    @classmethod
    async def get_by_session_id(cls, bot: Bot, s_id: int, is_group: bool):
        session_id = f"{'group' if is_group else 'private'}-{s_id}"
        recorder = cls._recorders.get((bot.self_id, session_id))
        if not recorder:
            recorder = Recorder(bot.self_id, session_id)
            cls._recorders[(bot.self_id, session_id)] = recorder
            response = await bot.call_api(
                f"get_{'group' if is_group else 'friend'}_msg_history",
                count=config.recorder_init_history_length,
                **{"group_id" if is_group else "user_id": s_id},
            )
            for msg in response["messages"]:
                recorder.append(msg)
            logger.info(f"get {len(recorder.msg_history)} messages from {session_id}")
        return recorder

    @classmethod
    async def get(cls, bot: Bot, event: Event):
        if hasattr(event, "group_id"):
            s_id = getattr(event, "group_id")
            is_group = True
        else:
            s_id = getattr(event, "user_id")
            is_group = False
        return await cls.get_by_session_id(bot, s_id, is_group)

    @property
    def cutoff(self):
        data_file = get_plugin_data_file(f"cutoff-{self.bot_id}.json")
        if not data_file.exists():
            return None
        return json.loads(data_file.read_text(encoding="utf-8")).get(self.session_id)

    @cutoff.setter
    def cutoff(self, value: int | None):
        data_file = get_plugin_data_file(f"cutoff-{self.bot_id}.json")
        if not data_file.exists():
            data = {}
        else:
            data = json.loads(data_file.read_text(encoding="utf-8"))
        if value is not None:
            data[self.session_id] = value
        elif self.session_id in data:
            del data[self.session_id]
        data_file.write_text(json.dumps(data), encoding="utf-8")

    def get_messages(self, count: int):
        messages: list[RecordMessage] = []
        for msg in reversed(self.msg_history):
            if len(messages) > count or msg.id == self.cutoff:
                break
            messages.append(msg)
        return messages[::-1]

    def get_msg(self, message_id: int):
        return next((m for m in self.msg_history if m.id == message_id), None)

    def append(self, event: MessageEvent | dict):
        if isinstance(event, dict):
            if not event["message"]:
                return
            event["post_type"] = "message"
            event = MessageEvent(**event)
        if not self.get_msg(event.message_id):
            self.msg_history.append(
                RecordMessage(
                    id=event.message_id,
                    time=event.time,
                    sender=event.sender,
                    message=event.original_message,
                )
            )
            if len(self.msg_history) > config.recorder_max_history_length:
                self.msg_history.pop(0)
            msg_text = event.original_message.to_rich_text()
            if msg_text == self.last_msg:
                self.msg_repeat_users.add(event.user_id)
            else:
                self.msg_repeat_users = {event.user_id}
                self.last_msg = msg_text

    def delete(self, message_id: int):
        for msg in self.msg_history:
            if msg.id == message_id:
                logger.info(f"delete message {message_id} from {self.session_id}")
                self.msg_history.remove(msg)
                msg_text = msg.message.to_rich_text()
                if (
                    msg_text == self.last_msg
                    and msg.sender.user_id in self.msg_repeat_users
                ):
                    self.msg_repeat_users.remove(msg.sender.user_id)


@event_preprocessor
async def _(bot: Bot, event: MessageEvent):
    recorder = await Recorder.get(bot, event)
    recorder.append(event)


@event_preprocessor
async def _(bot: Bot, event: GroupRecallNoticeEvent | FriendRecallNoticeEvent):
    recorder = await Recorder.get(bot, event)
    recorder.delete(event.message_id)


@Bot.on_called_api
async def _(bot, e, api: str, data, result):
    if not isinstance(bot, Bot):
        return
    if e or not result:
        return
    if api not in ["send_msg", "send_group_msg", "send_private_msg"]:
        return
    if "group_id" in data:
        s_id = data["group_id"]
        is_group = True
    else:
        s_id = data["user_id"]
        is_group = False
    recorder = await Recorder.get_by_session_id(bot, s_id, is_group)
    msg = await bot.get_msg(message_id=result["message_id"])
    recorder.append(msg)
