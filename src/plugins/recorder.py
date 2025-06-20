from pydantic import BaseModel

from nonebot import get_plugin_config, logger
from nonebot.message import event_preprocessor
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, GroupRecallNoticeEvent

class Config(BaseModel):
    recorder_max_history_length: int = 100

config = get_plugin_config(Config)

class Recorder:
    _recorders = dict[int, 'Recorder']()
    def __init__(self, group_id: int):
        self.group_id = group_id
        self.msg_history = list[GroupMessageEvent]()
        self.last_msg: str = None
        self.msg_repeat_count = 0

    @classmethod
    async def get(cls, group_id: int, bot: Bot):
        recorder = cls._recorders.get(group_id)
        if not recorder:
            recorder = Recorder(group_id)

            cls._recorders[group_id] = recorder
            response = await bot.get_group_msg_history(
                group_id=group_id,
                count=config.recorder_max_history_length
            )
            for msg in response["messages"]:
                if not msg["message"]:
                    continue
                msg["post_type"] = "message"
                recorder.append(GroupMessageEvent(**msg))
            logger.info(f"get {len(recorder.msg_history)} messages from group {group_id}")
        return recorder

    def get_msg(self, message_id: int):
        return next((e for e in self.msg_history if e.message_id == message_id), None)

    def append(self, event: GroupMessageEvent):
        if not self.get_msg(event.message_id):
            self.msg_history.append(event)
            if len(self.msg_history) > config.recorder_max_history_length:
                self.msg_history.pop(0)
            if (msg_text := event.original_message.to_rich_text()) == self.last_msg:
                self.msg_repeat_count += 1
            else:
                self.msg_repeat_count = 1
                self.last_msg = msg_text

    def delete(self, message_id: int):
        for idx, msg in enumerate(self.msg_history):
            if msg.message_id == message_id:
                logger.info(f"delete message {message_id} from group {self.group_id}")
                self.msg_history.pop(idx)
                if len(self.msg_history) - idx <= self.msg_repeat_count:
                    self.msg_repeat_count -= 1

    def get_reply_msg(self, event: GroupMessageEvent):
        for msg_seg in event.original_message:
            if msg_seg.type == "reply":
                return self.get_msg(int(msg_seg.data["id"]))

@event_preprocessor
async def _(bot: Bot, event: GroupMessageEvent):
    recorder = await Recorder.get(event.group_id, bot)
    recorder.append(event)

@event_preprocessor
async def _(bot: Bot, event: GroupRecallNoticeEvent):
    recorder = await Recorder.get(event.group_id, bot)
    recorder.delete(event.message_id)

@Bot.on_called_api
async def _(bot, e, api: str, data: dict[str], result):
    if not isinstance(bot, Bot):
        return
    if e or not result:
        return
    if api not in ["send_msg","send_group_msg"]:
        return
    msg_dict = await bot.get_msg(message_id=result["message_id"])
    msg_dict["post_type"] = "message"
    recorder = await Recorder.get(data["group_id"], bot)
    recorder.append(GroupMessageEvent(**msg_dict))
