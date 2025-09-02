import re

from nonebot import get_bot, get_bots, on_type, require
from nonebot.adapters.minecraft import BaseChatEvent, BaseDeathEvent, BaseJoinEvent
from nonebot.adapters.minecraft import Bot as MCBot
from nonebot.adapters.onebot.v11 import Bot as OneBot
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.rule import startswith
from pydantic import BaseModel

from .session_config import get_session_config, get_session_config_dir, load_config

require("nonebot_plugin_alconna")

from nonebot_plugin_alconna import (
    Alconna,
    Args,
    CommandMeta,
    Match,
    Subcommand,
    on_alconna,
)


class SConfig(BaseModel):
    mc_conn_servers: list[str] = []


SessionConfig = get_session_config(SConfig)


def is_enabled(session_config: SConfig = SessionConfig):
    return len(session_config.mc_conn_servers) > 0


mc_msg_handler = on_type(BaseChatEvent, rule=startswith("#"))
mc_death_handler = on_type(BaseDeathEvent)
mc_join_handler = on_type(BaseJoinEvent)
group_cmd_handler = on_alconna(
    Alconna(
        "mc-conn",
        Subcommand("switch", Args["server", str], help_text="切换到指定服务器"),
        Subcommand("send", Args["message", str], help_text="发送消息到服务器"),
        Subcommand("player", Args["name", str, None], help_text="查询玩家列表/信息"),
        Subcommand("time", help_text="查询服务器时间"),
        meta=CommandMeta(description="Minecraft 服务器互通指令"),
    ),
    rule=is_enabled,
    aliases={"mcc"},
    use_cmd_start=True,
    priority=0,
    block=True,
)


async def send_to_qq(server_name: str, username: str | None, message: str):
    for bot in get_bots().values():
        if not isinstance(bot, OneBot):
            continue
        for group_file in get_session_config_dir(bot.self_id).glob("group-*.yaml"):
            if server_name in load_config(group_file, SConfig).mc_conn_servers:
                group_id = int(group_file.name[6:-5])
                name = f"{server_name} {username}" if username else server_name
                await bot.send_group_msg(
                    group_id=group_id, message=f"<{name}> {message}"
                )


@mc_msg_handler.handle()
async def _(bot: MCBot, event: BaseChatEvent):
    text = event.get_plaintext()[1:]
    if text:
        await send_to_qq(event.server_name, event.player.nickname, text)
        await bot.send_rcon_cmd(command=f"msg {event.player.nickname} 消息已发送")


@mc_death_handler.handle()
async def _(event: BaseDeathEvent):
    if not event.player.nickname.startswith("bot_"):
        await send_to_qq(event.server_name, None, event.message.extract_plain_text())


recent_join_players: dict[str, int] = {}


@mc_join_handler.handle()
async def _(event: BaseJoinEvent):
    name = event.player.nickname
    if (
        not name.startswith("bot_")
        and recent_join_players.get(name, 0) + 60 < event.timestamp
    ):
        recent_join_players[name] = event.timestamp
        await send_to_qq(event.server_name, None, f"{name} 加入了游戏")


player_server_map = dict[str, str]()


async def get_mcbot(event: GroupMessageEvent, session_config: SConfig):
    player_server = player_server_map.get(event.get_session_id())
    if not player_server and len(session_config.mc_conn_servers) == 1:
        player_server = session_config.mc_conn_servers[0]
    if not player_server:
        await group_cmd_handler.finish("请先选择服务器", reply_message=True)
    try:
        return get_bot(player_server)
    except KeyError:
        await group_cmd_handler.finish("服务器未连接", reply_message=True)


@group_cmd_handler.assign("switch")
async def _(
    event: GroupMessageEvent,
    server: Match[str],
    session_config: SConfig = SessionConfig,
):
    if server.result in session_config.mc_conn_servers:
        player_server_map[event.get_session_id()] = server.result
        msg = f"已切换到服务器: {server.result}"
    else:
        msg = "服务器不存在"
    await group_cmd_handler.finish(msg, reply_message=True)


@group_cmd_handler.assign("send")
async def _(
    bot: OneBot,
    event: GroupMessageEvent,
    message: Match[str],
    session_config: SConfig = SessionConfig,
):
    mcbot = await get_mcbot(event, session_config)
    if not message.result:
        await group_cmd_handler.finish("请输入要发送的消息内容", reply_message=True)
    name = event.sender.card or event.sender.nickname
    await mcbot.send_msg(message=f"<Group {name}> {message.result}")
    await bot.group_poke(group_id=event.group_id, user_id=event.user_id)


@group_cmd_handler.assign("time")
async def _(event: GroupMessageEvent, session_config: SConfig = SessionConfig):
    mcbot = await get_mcbot(event, session_config)
    res = await mcbot.send_rcon_cmd(command="time query gametime")
    gametime = int(res[0].removeprefix("The time is "))
    day, daytime = divmod(gametime, 24000)
    hour, minute = divmod(daytime, 1000)
    f_hour = (hour + 6) % 24
    f_minute = int(minute * 60 / 1000)
    await group_cmd_handler.finish(
        f"当前游戏时间: {day}天 {f_hour}:{f_minute}", reply_message=True
    )


@group_cmd_handler.assign("player")
async def _(
    event: GroupMessageEvent,
    player: Match[str],
    session_config: SConfig = SessionConfig,
):
    mcbot = await get_mcbot(event, session_config)
    if not player.result:
        res = await mcbot.send_rcon_cmd(command="list")
        await group_cmd_handler.finish(
            f"当前玩家列表：{res[0].split(': ')[1].strip()}", reply_message=True
        )
    c = {"Health": "", "XpLevel": "", "Pos": ""}
    try:
        for i in c:
            data = await mcbot.send_rcon_cmd(
                command=f"data get entity {player.result} {i}"
            )
            c[i] = data[0].split(": ")[1].strip()
        text = f"玩家{player.result}信息：\n"
        text += f"生命值: {c['Health'].removesuffix('f')}\n"
        text += f"经验等级: {c['XpLevel']}\n"
        pos_pattern = r"\[(-?\d+)\.\d+d,\s(-?\d+)\.\d+d,\s(-?\d+)\.\d+d\]"
        pos_match = re.search(pos_pattern, c["Pos"])
        if pos_match:
            text += f"坐标: {', '.join(pos_match.groups())}"
    except Exception:
        text = "玩家不存在"
    await group_cmd_handler.finish(text, reply_message=True)


@group_cmd_handler.handle()
async def _(event: GroupMessageEvent, session_config: SConfig = SessionConfig):
    msg = "可用服务器: " + ", ".join(session_config.mc_conn_servers)
    player_server = player_server_map.get(event.get_session_id())
    if not player_server and len(session_config.mc_conn_servers) == 1:
        player_server = session_config.mc_conn_servers[0]
    if player_server:
        msg += f"\n当前服务器: {player_server}"
    await group_cmd_handler.finish(msg, reply_message=True)
