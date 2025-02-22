from pydantic import BaseModel

from nonebot import get_bot, get_plugin_config, logger, on_command, on_type
from nonebot.rule import startswith
from nonebot.params import Command, CommandArg
from nonebot.adapters.onebot.v11 import (
    Bot as OneBot,
    GroupMessageEvent,
    Message
)
from nonebot.adapters.minecraft import (
    Bot as MCBot,
    BaseChatEvent,
    BaseDeathEvent,
    NoticeEvent
)

class Config(BaseModel):
    mc_conn_onebot: int
    mc_conn_config: dict[str, list[str]]

config = get_plugin_config(Config)

def is_in_group(event: GroupMessageEvent):
    return str(event.group_id) in config.mc_conn_config

mc_msg_handler = on_type(BaseChatEvent, rule=startswith("#"))
mc_death_handler = on_type(BaseDeathEvent)
mc_notice_handler = on_type(NoticeEvent)
group_cmd_handler = on_command(
    "mcc",
    rule=is_in_group,
    aliases={("mcc", "time")},
    block=True
)

async def send_to_qq(server_name: str, username: str, message: str):
    try:
        onebot: OneBot = get_bot(str(config.mc_conn_onebot))
    except:
        logger.warning("OneBot not found")
        return
    for group_id in config.mc_conn_config:
        if server_name in config.mc_conn_config[group_id]:
            await onebot.send_group_msg(
                group_id=group_id,
                message=f"<{server_name}{username}> " + message
            )

@mc_msg_handler.handle()
async def _(event: BaseChatEvent):
    text = event.get_plaintext()[1:]
    if text:
        await send_to_qq(event.server_name, " " + event.get_user_id(), text)
        await mc_msg_handler.finish("消息已发送")

@mc_death_handler.handle()
async def _(event: BaseDeathEvent):
    await send_to_qq(event.server_name, "", event.message)

@mc_notice_handler.handle()
async def _(event: NoticeEvent):
    await send_to_qq(
        event.server_name,
        "",
        f"{event.player.nickname} {'加入' if event.sub_type == "join" else '退出'}了游戏"
    )

help_msg = """
/mcc <server-name> <message> - 发送消息到服务器
/mcc.time <server-name> - 查询服务器时间
"""

@group_cmd_handler.handle()
async def _(
    bot: OneBot,
    event: GroupMessageEvent,
    cmd: tuple[str, ...] = Command(),
    args: Message = CommandArg()
):
    cmd_type = "chat" if len(cmd) == 1 else cmd[1]
    parsed_args = args.extract_plain_text().split()
    enabled_servers = config.mc_conn_config[str(event.group_id)]
    if not parsed_args:
        msg = help_msg[1:] + "\n可用服务器: " + ", ".join(enabled_servers)
        await group_cmd_handler.finish(msg, reply_message=True)
    if parsed_args[0] not in enabled_servers:
        await group_cmd_handler.finish("服务器不存在", reply_message=True)
    try:
        mcbot: MCBot = get_bot(parsed_args[0])
    except:
        await group_cmd_handler.finish("服务器未连接", reply_message=True)
    if cmd_type == "chat":
        if len(parsed_args) == 1:
            await group_cmd_handler.finish("请输入要发送的消息内容", reply_message=True)
        name = event.sender.card or event.sender.nickname
        await mcbot.send_msg(message=f"<Group {name}> " + " ".join(parsed_args[1:]))
        await bot.call_api("group_poke", group_id=event.group_id, user_id=event.user_id)
    elif cmd_type == "time":
        res = await mcbot.send_rcon_cmd(command="time query gametime")
        gametime = int(res[0].removeprefix("The time is "))
        day, daytime = divmod(gametime, 24000)
        hour, minute = divmod(daytime, 1000)
        f_hour = (hour + 6) % 24
        f_minute = int(minute * 60 / 1000)
        await group_cmd_handler.finish(f"当前游戏时间: {day}天 {f_hour}:{f_minute}", reply_message=True)
