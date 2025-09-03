import asyncio
import json
import time

from jmcomic import JmModuleConfig
from nonebot import get_plugin_config, logger, on_command, require
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg
from pydantic import BaseModel

require("nonebot_plugin_localstore")

from nonebot_plugin_localstore import get_plugin_cache_dir, get_plugin_data_file

from .session_config import get_session_config


class Config(BaseModel):
    jm_max_downloads: int = 3


class SConfig(BaseModel):
    jm_enabled: bool = False


config = get_plugin_config(Config)

cache_dir = get_plugin_cache_dir()
usage_file = get_plugin_data_file("usage.json")

jm_option = JmModuleConfig.option_class().construct(
    {
        "dir_rule": {"base_dir": str(cache_dir)},
        "plugins": {
            "after_album": [
                {
                    "plugin": "img2pdf",
                    "kwargs": {
                        "pdf_dir": str(cache_dir),
                        "filename_rule": "Apdfname",
                        "delete_original_file": True,
                    },
                }
            ],
        },
    }
)
JmModuleConfig.EXECUTOR_LOG = (  # type: ignore
    lambda t, m: logger.info(m) if t.startswith("album") else None
)
JmModuleConfig.AFIELD_ADVICE["pdfname"] = lambda a: f"[{a.id}] {a.title}"


def is_enable(session_config: SConfig = get_session_config(SConfig)):
    return session_config.jm_enabled


command = on_command(
    "jmcomic",
    rule=is_enable,
    aliases={"jm"},
    force_whitespace=True,
    priority=0,
    block=True,
)


def get_usage_data() -> dict[str, dict[str, int]]:
    if usage_file.exists():
        return json.loads(usage_file.read_text(encoding="utf-8"))
    return {}


user_locks: dict[str, asyncio.Lock] = {}


@command.handle()
async def jmcomic(event: MessageEvent, args: Message = CommandArg()):
    if len(args) == 0:
        await command.finish("请指定漫画ID", reply_message=True)
    comic_id = args.extract_plain_text().strip()
    if not comic_id.isdigit():
        await command.finish("漫画ID格式错误", reply_message=True)

    def get_pdf_path():
        for path in cache_dir.glob("*.pdf"):
            if path.name.startswith(f"[{comic_id}]"):
                return path

    user_id = str(event.user_id)
    lock = user_locks.setdefault(user_id, asyncio.Lock())
    if lock.locked():
        await command.finish("请等待处理完成后再试", reply_message=True)

    async with lock:
        date = time.strftime("%Y-%m-%d")
        if get_usage_data().get(date, {}).get(user_id, 0) >= config.jm_max_downloads:
            await command.finish("已达到每日下载次数上限", reply_message=True)

        pdf_path = get_pdf_path()
        if not pdf_path:
            await command.send(f"正在下载 {comic_id}，请稍等...", reply_message=True)
            await asyncio.to_thread(jm_option.download_album, comic_id)
            pdf_path = get_pdf_path()
        if not pdf_path:
            await command.finish("下载漫画失败", reply_message=True)

        await command.send(f"正在发送 {pdf_path.name}，请稍等...", reply_message=True)
        try:
            await command.send(
                MessageSegment(
                    "file",
                    {
                        "name": pdf_path.name,
                        "file": str(pdf_path),
                    },
                )
            )
        except Exception as e:
            logger.error(f"send file failed: {e}")
            await command.finish("发送漫画失败", reply_message=True)

        usage_data = get_usage_data()
        d = usage_data.setdefault(date, {})
        d[user_id] = d.get(user_id, 0) + 1
        usage_file.write_text(json.dumps(usage_data))
