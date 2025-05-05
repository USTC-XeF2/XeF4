import re
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
    BaseJoinEvent
)

class Config(BaseModel):
    mc_conn_onebot: int
    mc_conn_config: dict[str, list[str]]

config = get_plugin_config(Config)

def is_in_group(event: GroupMessageEvent):
    return str(event.group_id) in config.mc_conn_config

mc_msg_handler = on_type(BaseChatEvent, rule=startswith("#"))
mc_death_handler = on_type(BaseDeathEvent)
mc_join_handler = on_type(BaseJoinEvent)
group_cmd_handler = on_command(
    "mcc",
    rule=is_in_group,
    aliases={("mcc", "send"), ("mcc", "player"), ("mcc", "time")},
    force_whitespace=True,
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
async def _(bot: MCBot, event: BaseChatEvent):
    text = event.get_plaintext()[1:]
    if text:
        await send_to_qq(event.server_name, " " + event.player.nickname, text)
        await bot.send_rcon_cmd(command=f"msg {event.player.nickname} 消息已发送")

@mc_death_handler.handle()
async def _(event: BaseDeathEvent):
    if not event.player.nickname.startswith("bot_"):
        await send_to_qq(event.server_name, "", event.message)

@mc_join_handler.handle()
async def _(event: BaseJoinEvent):
    if not event.player.nickname.startswith("bot_"):
        await send_to_qq(event.server_name, "", f"{event.player.nickname} 加入了游戏")

help_msg = """
/mcc [server-name] - 切换到指定服务器
/mcc.send <message> - 发送消息到服务器
/mcc.player [player-name] - 查询玩家信息
/mcc.time - 查询服务器时间
"""

player_server_map = dict[str, str]()

@group_cmd_handler.handle()
async def _(
    bot: OneBot,
    event: GroupMessageEvent,
    cmd: tuple[str, ...] = Command(),
    args: Message = CommandArg()
):
    parsed_args = args.extract_plain_text().split()
    enabled_servers = config.mc_conn_config[str(event.group_id)]
    if len(enabled_servers) == 1:
        present_server = enabled_servers[0]
    else:
        present_server = player_server_map.get(event.get_session_id())
    if len(cmd) == 1:
        if not parsed_args:
            msg = help_msg[1:] + "\n可用服务器: " + ", ".join(enabled_servers)
            if present_server:
                msg += f"\n当前服务器: {present_server}"
        elif parsed_args[0] in enabled_servers:
            player_server_map[event.get_session_id()] = parsed_args[0]
            msg = f"已切换到服务器: {parsed_args[0]}"
        else:
            msg = "服务器不存在"
        await group_cmd_handler.finish(msg, reply_message=True)
    if not present_server:
        await group_cmd_handler.finish("请先选择服务器", reply_message=True)
    try:
        mcbot: MCBot = get_bot(present_server)
    except:
        await group_cmd_handler.finish("服务器未连接", reply_message=True)
    if cmd[1] == "send":
        if not parsed_args:
            await group_cmd_handler.finish("请输入要发送的消息内容", reply_message=True)
        name = event.sender.card or event.sender.nickname
        await mcbot.send_msg(message=f"<Group {name}> " + " ".join(parsed_args))
        await bot.call_api("group_poke", group_id=event.group_id, user_id=event.user_id)
    elif cmd[1] == "time":
        res = await mcbot.send_rcon_cmd(command="time query gametime")
        gametime = int(res[0].removeprefix("The time is "))
        day, daytime = divmod(gametime, 24000)
        hour, minute = divmod(daytime, 1000)
        f_hour = (hour + 6) % 24
        f_minute = int(minute * 60 / 1000)
        await group_cmd_handler.finish(f"当前游戏时间: {day}天 {f_hour}:{f_minute}", reply_message=True)
    elif cmd[1] == "player":
        if not parsed_args:
            res = await mcbot.send_rcon_cmd(command="list")
            await group_cmd_handler.finish(
                f"当前玩家列表：{res[0].split(': ')[1].strip()}",
                reply_message=True
            )
        c = {"Health": "", "XpLevel": "", "Pos": ""}
        try:
            player = parsed_args[0]
            for i in c:
                data = await mcbot.send_rcon_cmd(command=f"data get entity {player} {i}")
                c[i] = data[0].split(": ")[1].strip()
            text = f"玩家{player}信息：\n"
            text += f"生命值: {c['Health'].removesuffix('f')}\n"
            text += f"经验等级: {c['XpLevel']}\n"
            pos_pattern = r"\[(-?\d+)\.\d+d,\s(-?\d+)\.\d+d,\s(-?\d+)\.\d+d\]"
            text += f"坐标: {', '.join(re.search(pos_pattern, c['Pos']).groups())}"
        except:
            await group_cmd_handler.finish("玩家不存在", reply_message=True)
        await group_cmd_handler.finish(text, reply_message=True)
