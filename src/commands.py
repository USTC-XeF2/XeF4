import re
import json
import asyncio
from mcstatus import JavaServer

from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot_plugin_localstore import get_config_dir

config_dir = get_config_dir("command")

async def poke(matcher: Matcher, bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    """
    <qq|@> [times=1]
    戳一戳指定qq号的用户，上限为5次，冷却时间60s
    """
    times = "1"
    if len(args) == 0:
        if not event.to_me:
            await matcher.finish("请指定戳一戳的对象", reply_message=True)
        user_id = bot.self_id
    elif len(args) == 1:
        if args[0].type == "at":
            user_id = args[0].data["qq"]
        elif args[0].type == "text":
            l: list[str] = args[0].data["text"].split()
            user_id = l[0]
            if len(l) == 2:
                times = l[1]
        else:
            await matcher.finish("参数类型错误", reply_message=True)
    elif len(args) == 2 and args[0].type == "at":
        user_id = args[0].data["qq"]
        times = str(args[1].data["text"]).strip()
    else:
        await matcher.finish("参数错误", reply_message=True)

    if not user_id.isdigit():
        await matcher.finish("QQ号格式错误，请直接输入QQ号或@群成员", reply_message=True)
    if not await bot.get_group_member_info(group_id=event.group_id, user_id=user_id):
        await matcher.finish(f"{user_id}不在群内", reply_message=True)
    if not times.isdigit():
        await matcher.finish("戳一戳次数必须为数字", reply_message=True)
    times = int(times)
    if not 1 <= times <= 5:
        await matcher.finish("戳一戳的次数限制在1-5间", reply_message=True)

    for _ in range(times):
        await bot.call_api("group_poke", group_id=event.group_id, user_id=user_id)
        await asyncio.sleep(0.1)

async def _get_server_status(url: str, max_try: int = 3):
    for _ in range(max_try):
        try:
            return await JavaServer.lookup(url).async_status()
        except IOError as e:
            if "Received invalid status response packet." in e.args:
                return True
        except Exception:
            continue
    return False

async def _server_info(servers: dict[str, dict[str, str]], name_or_ip: str):
    if not name_or_ip:
        return "服务器列表\n--------------------\n" + "\n".join(servers.keys())
    if name_or_ip == "-a":
        checked_server = {name: server for name, server in servers.items() if "url" in server}
        info = "在线服务器状态列表\n--------------------"
        status_tasks = [_get_server_status(server["url"], max_try=2)
                        for server in checked_server.values()]
        status_results = await asyncio.gather(*status_tasks)
        for name, status in zip(checked_server.keys(), status_results):
            if not isinstance(status, bool):
                info += f"\n{name}: {round(status.latency, 1)}ms {status.players.online}/{status.players.max}人在线"
        return info

    if (server := servers.get(name_or_ip := name_or_ip.lower())):
        if "redirect" in server:
            server = servers[server["redirect"]]
        server_addr = server["url"]
        server_name = f"{name_or_ip}({server_addr})"
    else:
        addr_pattern = r'^(?:([a-zA-Z0-9.-]+)|(?:\[([a-f0-9:]+)\]))(?::(\d+))?$'
        match = re.match(addr_pattern, name_or_ip)
        if not match:
            return "服务器地址格式错误"
        ipv4, ipv6, port = match.groups()
        host = ipv4 or ipv6
        if not (ipv6 or "." in host):
            return "服务器地址格式错误"
        server_addr = name_or_ip
        if port:
            port = int(port)
            if not (0 < port < 65536):
                return "端口号必须在1-65535之间"
            server_name = name_or_ip
        else:
            server_name = f"{name_or_ip}(:25565)"
            server_addr = f"{name_or_ip}:25565"

    status = await _get_server_status(server_addr)
    if isinstance(status, bool):
        if status:
            return "无法解析为Java服务器"
        else:
            return "服务器连接失败"
    motd = "".join([i.strip(" ") for i in status.motd.parsed if isinstance(i, str)])
    info = f"{server_name}\n--------------------\n" \
            f"{motd}\n--------------------\n" \
            f"版本：{status.version.name}\n" \
            f"延迟：{int(status.latency)}ms\n" \
            f"在线人数：{status.players.online}/{status.players.max}"
    player_list = [player.name for player in (status.players.sample or []) if player.name != "Anonymous Player"]
    if player_list:
        info += f"\n玩家列表：{', '.join(player_list)}"
    return info

async def server_info(matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()):
    """
    [name|ip|flag]
    获取服务器名称或ip指向的MC服务器信息
    使用 -a 标志获取当前在线服务器信息概览
    """
    with (config_dir / "mc-servers.json").open() as rf:
        data = json.load(rf)
    group_config = data["config"].get(str(event.group_id), [])
    await matcher.finish(await _server_info(
        {name: data["servers"][name] for name in group_config},
        args.extract_plain_text().strip()
    ), reply_message=True)
