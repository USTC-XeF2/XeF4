import asyncio
import io
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime

import matplotlib.pyplot as plt
import yaml
from matplotlib.dates import DateFormatter, date2num
from matplotlib.font_manager import fontManager
from matplotlib.ticker import MaxNLocator
from mcstatus import JavaServer
from mcstatus.responses import JavaStatusResponse
from nonebot import get_plugin_config, logger, require
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment
from pydantic import BaseModel

from .session_config import check_enable

require("nonebot_plugin_alconna")
require("nonebot_plugin_apscheduler")
require("nonebot_plugin_localstore")

from nonebot_plugin_alconna import (
    Alconna,
    Args,
    CommandMeta,
    Match,
    Option,
    Query,
    Subcommand,
    on_alconna,
)
from nonebot_plugin_apscheduler import scheduler
from nonebot_plugin_localstore import get_plugin_data_dir, get_plugin_data_file


class Config(BaseModel):
    mc_status_min_record_interval: int = 600
    mc_status_max_history_days: int = 30


class SConfig(BaseModel):
    mc_status_enabled: bool = False


config = get_plugin_config(Config)

fontManager.addfont("./src/resources/unifont.otf")
plt.rcParams["font.family"] = ["Unifont"]
plt.rcParams["axes.unicode_minus"] = False


class Server(BaseModel):
    name: str
    aliases: frozenset[str] = frozenset()
    url_list: list[str]


@dataclass
class ServerStatus:
    server: Server
    online_urls: list[tuple[str, float]]
    status: JavaStatusResponse | None
    error: str | None


command = on_alconna(
    Alconna(
        "mc-status",
        Subcommand(
            "history|his",
            Args["server", str],
            Args["days", int, 7],
            help_text="获取指定服务器历史在线人数，默认为近7天",
        ),
        Subcommand(
            "list|ls",
            Option("--all|-a", help_text="展示离线服务器(默认不展示)"),
            help_text="获取已配置的所有服务器状态概览",
        ),
        Args["server", str, None],
        meta=CommandMeta(description="获取 Minecraft 服务器信息", compact=True),
    ),
    rule=check_enable(SConfig, "mc_status_enabled"),
    aliases={"mcs", "s"},
    priority=0,
    block=True,
)


server_example = """# - name: default
#   aliases: []
#   url_list:
#     - localhost:25565
"""


def get_servers(group_id: int) -> list[Server]:
    data_file = get_plugin_data_file(f"server-{group_id}.yaml")
    if not data_file.exists():
        with data_file.open("w", encoding="utf-8") as wf:
            wf.write(server_example)
        return []
    with data_file.open(encoding="utf-8") as rf:
        data = yaml.safe_load(rf)
    if data:
        return [Server.model_validate(s) for s in data]
    return []


def get_server(group_id: int, name_or_alias: str):
    servers = get_servers(group_id)
    for server in servers:
        if server.name == name_or_alias or name_or_alias in server.aliases:
            return server
    return None


def get_server_history(group_id: int, server_name: str) -> list[dict]:
    history_file = get_plugin_data_file(f"history-{group_id}.json")
    if not history_file.exists():
        return []
    return json.loads(history_file.read_text(encoding="utf-8")).get(server_name, [])


def add_server_history(group_id: int, server_name: str, online_player: int):
    history_file = get_plugin_data_file(f"history-{group_id}.json")
    if history_file.exists():
        all_servers = json.loads(history_file.read_text(encoding="utf-8"))
    else:
        all_servers = {}
    history = all_servers.get(server_name, [])
    now = int(time.time())
    if (
        history
        and now - history[-1]["time"] < config.mc_status_min_record_interval
        and history[-1]["online"] == online_player
    ):
        return
    logger.info(f"add history for {server_name!r}, with {online_player} players online")
    history.append({"time": now, "online": online_player})
    all_servers[server_name] = [
        entry
        for entry in history
        if now - entry["time"] < config.mc_status_max_history_days * 86400
    ]
    history_file.write_text(json.dumps(all_servers), encoding="utf-8")


async def get_server_status(server: Server, max_try: int):
    online_urls = []
    status: JavaStatusResponse | None = None
    error: str | None = None

    async def check_url(url: str):
        for _ in range(max_try):
            try:
                resp = await JavaServer.lookup(url).async_status()
                return resp
            except IOError as e:
                if "Received invalid status response packet." in e.args:
                    raise RuntimeError("无法解析为Java服务器")
            except Exception:
                continue
        return None

    tasks = [check_url(url) for url in server.url_list]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for url, result in zip(server.url_list, results):
        if isinstance(result, JavaStatusResponse):
            online_urls.append((url, result.latency))
            if not status:
                status = result
        elif isinstance(result, Exception) and not error:
            error = str(result)

    return ServerStatus(server, online_urls, status, error)


@command.assign("list")
async def _(
    event: GroupMessageEvent, all=Query("subcommands.list.options.all", default=None)
):
    servers = get_servers(event.group_id)
    status_tasks = [get_server_status(server, max_try=2) for server in servers]
    results = await asyncio.gather(*status_tasks)
    if all.result is None:
        results = [r for r in results if r.online_urls]
    results.sort(
        key=lambda x: x.status.players.online if x.status else -1, reverse=True
    )
    info = "服务器状态列表\n----------------"
    for r in results:
        if r.online_urls and r.status:
            add_server_history(event.group_id, r.server.name, r.status.players.online)
            min_latency = min(r.online_urls, key=lambda x: x[1])[1]
            players = r.status.players
            info_text = f"{min_latency:.1f}ms {players.online}/{players.max}人在线"
        else:
            info_text = r.error or "无法连接到服务器"
        info += f"\n{r.server.name}: {info_text}"
    await command.finish(info, reply_message=True)


@command.assign("history")
async def _(event: GroupMessageEvent, server: Match[str], days: Match[int]):
    valid_server = get_server(event.group_id, server.result)
    if not valid_server:
        await command.finish("无此服务器", reply_message=True)
    if not 0 < days.result <= config.mc_status_max_history_days:
        await command.finish(
            f"请提供有效的天数（1-{config.mc_status_max_history_days}）",
            reply_message=True,
        )

    history = get_server_history(event.group_id, valid_server.name)
    start_time = time.time() - days.result * 86400
    filtered_history = [entry for entry in history if entry["time"] >= start_time]
    if len(filtered_history) <= 1:
        await command.finish("历史记录不足", reply_message=True)

    optimized_history = []
    for i, entry in enumerate(filtered_history):
        if i == 0 or i == len(filtered_history) - 1:
            optimized_history.append(entry)
        else:
            prev_online = filtered_history[i - 1]["online"]
            next_online = filtered_history[i + 1]["online"]
            if not (prev_online == entry["online"] == next_online):
                optimized_history.append(entry)

    times = date2num(
        [datetime.fromtimestamp(entry["time"]) for entry in optimized_history]
    )
    onlines = [entry["online"] for entry in optimized_history]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(times, onlines, marker=".", linestyle="-")
    ax.xaxis.set_major_formatter(DateFormatter("%m-%d %H:%M"))
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_title(f"{valid_server.name} 近{days.result}天在线人数变化")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, dpi=200, format="png")
    plt.close(fig)
    await command.finish(MessageSegment.image(buf), reply_message=True)


@command.handle()
async def _(event: GroupMessageEvent, server: Match[str]):
    name_or_ip = server.result
    if not name_or_ip:
        await command.finish("请提供服务器名称或IP地址", reply_message=True)
    valid_server = get_server(event.group_id, name_or_ip)
    is_known = valid_server is not None
    if not valid_server:
        addr_pattern = r"^(?:([a-zA-Z0-9.-]+)|(?:\[([a-f0-9:]+)\]))(?::(\d+))?$"
        match = re.match(addr_pattern, name_or_ip)
        if match:
            ipv4, ipv6, port = match.groups()
            if (ipv6 or "." in ipv4) and (not port or (0 < int(port) < 65536)):
                valid_server = Server(name=name_or_ip, url_list=[name_or_ip])
    if not valid_server:
        await command.finish("地址格式错误或无此服务器", reply_message=True)
    result = await get_server_status(valid_server, max_try=3)
    if not (result.online_urls and result.status):
        await command.finish("无法连接到服务器", reply_message=True)
    motd = "".join(
        [i.strip(" ") for i in result.status.motd.parsed if isinstance(i, str)]
    )
    players = result.status.players
    player_list = [
        player.name
        for player in (players.sample or [])
        if player.id != "00000000-0000-0000-0000-000000000000"
    ]
    SPLITER = "--------------------\n"
    info = f"{motd}\n{SPLITER}"
    if is_known:
        add_server_history(event.group_id, valid_server.name, players.online)
        online_urls = sorted(result.online_urls, key=lambda x: x[1])
        for url, latency in online_urls:
            info += f"{url}: {latency:.1f}ms\n"
        info += SPLITER
    info += f"版本：{result.status.version.name}\n"
    if not is_known:
        info += f"延迟：{result.status.latency:.1f}ms\n"
    info += f"在线人数：{players.online}/{result.status.players.max}"
    if player_list:
        show_ellipsis = len(player_list) > 5 or len(player_list) < players.online
        info += f"\n玩家列表：{', '.join(player_list[:5]) + (' ...' if show_ellipsis else '')}"

    await command.finish(info, reply_message=True)


@scheduler.scheduled_job("cron", minute=0)
async def _():
    pattern = re.compile(r"server-(\d+)\.yaml")
    for file in get_plugin_data_dir().glob("server-*.yaml"):
        match = pattern.match(file.name)
        if not match:
            continue

        group_id = int(match.group(1))
        try:
            with file.open(encoding="utf-8") as rf:
                data = yaml.safe_load(rf)
        except Exception as e:
            logger.warning(f"failed to read {file}: {e}")
            continue
        if not data:
            continue

        for server in map(Server.model_validate, data):
            status = (await get_server_status(server, max_try=2)).status
            if status:
                add_server_history(group_id, server.name, status.players.online)
