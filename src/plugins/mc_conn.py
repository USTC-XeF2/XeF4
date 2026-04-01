import re

from nonebot import get_bot, get_bots, on_type, require
from nonebot.adapters.minecraft import Bot as MCBot
from nonebot.adapters.minecraft import (
    PlayerChatEvent,
    PlayerDeathEvent,
    PlayerJoinEvent,
)
from nonebot.adapters.onebot.v11 import Bot as OneBot
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.rule import startswith

require("nonebot_plugin_alconna")
require("nonebot_plugin_session_config")

from nonebot_plugin_alconna import (
    Alconna,
    Args,
    CommandMeta,
    Match,
    Subcommand,
    on_alconna,
)
from nonebot_plugin_session_config import (
    BaseSessionConfig,
    check_condition,
    traverse_session_configs,
)


class SessionConfig(BaseSessionConfig):
    mc_conn_servers: list[str] = []


mc_msg_handler = on_type(PlayerChatEvent, rule=startswith("#"))
mc_death_handler = on_type(PlayerDeathEvent)
mc_join_handler = on_type(PlayerJoinEvent)
group_cmd_handler = on_alconna(
    Alconna(
        "mc-conn",
        Subcommand("switch", Args["server", str], help_text="切换到指定服务器"),
        Subcommand("send", Args["message", str], help_text="发送消息到服务器"),
        Subcommand("player", Args["name", str, None], help_text="查询玩家列表/信息"),
        Subcommand("time", help_text="查询服务器时间"),
        meta=CommandMeta(description="Minecraft 服务器互通指令"),
    ),
    rule=check_condition(SessionConfig, lambda c: len(c.mc_conn_servers) > 0),
    aliases={"mcc"},
    priority=0,
    block=True,
)


async def send_to_qq(server_name: str, username: str | None, message: str):
    for bot in get_bots().values():
        if not isinstance(bot, OneBot):
            continue
        for scene, config in traverse_session_configs(
            bot.self_id, SessionConfig
        ).items():
            if scene[0] == "group" and server_name in config.mc_conn_servers:
                name = f"{server_name} {username}" if username else server_name
                await bot.send_group_msg(
                    group_id=int(scene[1]), message=f"<{name}> {message}"
                )


@mc_msg_handler.handle()
async def _(bot: MCBot, event: PlayerChatEvent):
    text = event.get_plaintext()[1:]
    if text:
        await send_to_qq(event.server_name, event.player.nickname, text)
        await bot.send_rcon_cmd(command=f"msg {event.player.nickname} 消息已发送")


@mc_death_handler.handle()
async def _(event: PlayerDeathEvent):
    if not event.player.nickname.startswith("bot_"):
        await send_to_qq(event.server_name, None, event.get_event_description())


recent_join_players: dict[str, int] = {}


@mc_join_handler.handle()
async def _(event: PlayerJoinEvent):
    name = event.player.nickname
    if (
        not name.startswith("bot_")
        and recent_join_players.get(name, 0) + 60 < event.timestamp
    ):
        recent_join_players[name] = event.timestamp
        await send_to_qq(event.server_name, None, f"{name} 加入了游戏")


player_server_map = dict[str, str]()


async def get_mcbot(event: GroupMessageEvent, session_config: SessionConfig):
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
    session_config: SessionConfig,
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
    session_config: SessionConfig,
):
    mcbot = await get_mcbot(event, session_config)
    if not message.result:
        await group_cmd_handler.finish("请输入要发送的消息内容", reply_message=True)
    name = event.sender.card or event.sender.nickname
    await mcbot.send_msg(message=f"<Group {name}> {message.result}")
    await bot.group_poke(group_id=event.group_id, user_id=event.user_id)


@group_cmd_handler.assign("time")
async def _(event: GroupMessageEvent, session_config: SessionConfig):
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
    name: Match[str],
    session_config: SessionConfig,
):
    mcbot = await get_mcbot(event, session_config)
    if not name.result:
        res = await mcbot.send_rcon_cmd(command="list")
        await group_cmd_handler.finish(
            f"当前玩家列表：{res[0].split(': ')[1].strip()}", reply_message=True
        )
    c = {"Health": "", "XpLevel": "", "Pos": ""}
    try:
        for i in c:
            data = await mcbot.send_rcon_cmd(
                command=f"data get entity {name.result} {i}"
            )
            c[i] = data[0].split(": ")[1].strip()
        text = f"玩家{name.result}信息：\n"
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
async def _(event: GroupMessageEvent, session_config: SessionConfig):
    msg = "可用服务器: " + ", ".join(session_config.mc_conn_servers)
    player_server = player_server_map.get(event.get_session_id())
    if not player_server and len(session_config.mc_conn_servers) == 1:
        player_server = session_config.mc_conn_servers[0]
    if player_server:
        msg += f"\n当前服务器: {player_server}"
    await group_cmd_handler.finish(msg, reply_message=True)
