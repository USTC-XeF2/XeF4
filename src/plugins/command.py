from nonebot import require

require("nonebot_plugin_localstore")

import json
import time
import inspect

from nonebot import logger, on_command
from nonebot.params import CommandArg, Depends
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot_plugin_localstore import get_plugin_config_file

ec_file = get_plugin_config_file("enable-commands.json")
if not ec_file.exists():
    ec_file.write_text("{}")
usage_times_dir = get_plugin_config_file("usage_times")
if not usage_times_dir.exists():
    usage_times_dir.mkdir(parents=True)

class Command:
    commands = list['Command']()
    def __init__(self, name: str, func, aliases: set[str] = None, max_usage_times: int = -1):
        Command.commands.append(self)
        self.name = name
        self.func = func
        self.aliases = aliases or set()
        self.max_usage_times = max_usage_times if max_usage_times >= 0 else float("inf")
        self.command_handler = on_command(
            self.name,
            rule=self.is_enable,
            aliases=self.aliases,
            priority=0,
            block=True
        )
        self.command_handler.handle(parameterless=[Depends(self.check_usage_times)])(self.func)
        logger.info(f"register command: {self.name}")

    def __del__(self):
        self.command_handler.destroy()
        logger.info(f"unregister command: {self.name}")

    def is_enable(self, event: GroupMessageEvent):
        with ec_file.open() as rf:
            enable_commands: dict[str, list[str]] = json.load(rf)
        return self.name in enable_commands.get(str(event.group_id), [])

    async def check_usage_times(self, event: GroupMessageEvent):
        times_file = usage_times_dir / time.strftime("%Y%m%d.json")
        times: dict[str, dict[str, int]]
        if times_file.exists():
            times = json.loads(times_file.read_text())
        else:
            times = {}
        times.setdefault(self.name, {})
        session_id = event.get_session_id()
        times[self.name].setdefault(session_id, 0)
        if times[self.name][session_id] >= self.max_usage_times:
            await self.command_handler.finish("命令已达到最大使用次数", reply_message=True)
        times[self.name][session_id] += 1
        times_file.write_text(json.dumps(times, indent=4))

help_cmd = on_command(
    "help",
    priority=0,
    block=True
)

def _make_help(cmd: Command, show_info: bool = True):
    help_string = f"/{cmd.name}"
    if cmd.aliases:
        help_string += " (/" + " /".join(cmd.aliases) + ")"
    if show_info:
        doc_string = (inspect.getdoc(cmd.func) or "").split("\n", maxsplit=1)
        help_string += " " + doc_string[0]
        if len(doc_string) > 1:
            help_string += "\n" + doc_string[1]
    return help_string

@help_cmd.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    parsed_args = args.extract_plain_text().split()
    enabled_commands = [cmd for cmd in Command.commands if cmd.is_enable(event)]
    if not enabled_commands:
        await help_cmd.finish("群聊无可用命令", reply_message=True)
    if len(parsed_args) == 0:
        help_text = "输入'/help [command]'来获取命令的帮助信息\n可用命令列表："
        for cmd in enabled_commands:
            help_text += f"\n- {_make_help(cmd, show_info=False)}"
        await help_cmd.finish(help_text, reply_message=True)
    if len(parsed_args) > 1:
        await help_cmd.finish("参数过多", reply_message=True)
    for cmd in enabled_commands:
        if parsed_args[0] == cmd.name or parsed_args[0] in cmd.aliases:
            await help_cmd.finish(_make_help(cmd), reply_message=True)
    await help_cmd.finish(f"命令不存在", reply_message=True)
