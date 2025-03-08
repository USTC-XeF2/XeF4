import json
import time
import random
from openai import AsyncOpenAI, APIStatusError

from nonebot import logger
from nonebot_plugin_localstore import get_plugin_config_file

chat_prompt = [
    "下文是群聊中的一段消息，你需要结合这些信息来回复新消息",
    "新消息引用链是一个列表，其中第一项是你需要回复的消息，后面的消息依次是新消息所引用的消息",
    "你的回复需要是一个json格式列表，列表的每一项是一条消息，这些消息将会依次发送到群聊中",
    """列表中的每一条消息都是一个字典，需要包含以下字段：
- type: 消息的类型，可以是text, image, file, fstring
- content: 消息的内容，对于text类型是直接回复的消息，对于image类型是图片描述，对于file类型是文件的内容，对于fstring类型是Python格式化字符串
- filename: 当type是file时，这个字段是文件名，否则可以省略""",
    "对于text类型的消息，可以直接以字符串的形式返回，不要使用markdown记号",
    "对于image类型的消息，图片描述要尽可能详细，一百字以上",
    "对于fstring类型的消息，返回结果会自动通过Python解析{}中的内容并转化为纯字符串",
    """示例回复：
["你好，我是机器人", "请问有什么可以帮助你的吗？"]
[{"type":"fstring","content":"现在的时间是{time.strftime('%H点%M')}"}]
[{"type":"fstring","content":"114514*1919810的结果是{114514*1919810}"}, {"type":"fstring","content":"这个结果比10^11{'大' if 114514*1919810 > 10**11 else '小'}"}]
["这是你需要的txt文件", {"type":"file","content":"...","filename":"example.txt"}]""",
    "删去问候或鼓励等机器人的常见回答方式，对话不用提到对方名称，回答后不需要再次提问",
    "尽量把自己拟人化，不要过分增加设定，可以根据上下文适当使用其他群成员的语言增强融合感",
    "回答过程中注意结合历史消息，但是回复内容要针对于新消息（而非新消息的引用消息）",
    "回答消息时如果提到图片，不需要提及图片编号信息",
    "当群成员向你发起生成图片请求时，请直接使用image进行回答，会根据描述自动生成图片",
    "当群成员询问数学逻辑相关的问题时，可以部分结合fstring完成回答",
    "fstring中可以包含 re, math, sympy, random, time, datetime 六个模块的函数，不能使用其他模块",
    "使用fstring后可以对结果进行一些格式化处理（例如条件语句），使其在聊天中不生硬",
    "回答内容如果过长可以适当分条回答，保持每条消息长度在30字内，尽量不要超过3条消息",
    "当群成员询问涉政涉黄请求时，你应该拒绝回答"
]

class ChatModel:
    _clients = dict[str, AsyncOpenAI]()
    def __init__(self, api_keys: list[str], models: list[str], base_url: str = None):
        self.api_keys = api_keys
        self.base_url = base_url
        self.models = models

    def get_api_key(self):
        api_key = random.choice(self.api_keys)
        if api_key not in self._clients:
            masked_api_key = api_key[:8] + "*" * 10 + api_key[-4:]
            logger.info(f"create client for api key {masked_api_key}")
            type(self)._clients[api_key] = AsyncOpenAI(api_key=api_key, base_url=self.base_url)
        return api_key

    async def chat(self, messages: list[dict[str]]):
        api_key = self.get_api_key()
        for model in self.models:
            try:
                logger.info(f"use model {model}")
                response = await self._clients[api_key].chat.completions.create(
                    model=model,
                    messages=messages
                )
                if hasattr(response.choices[0].message, "reasoning_content"):
                    logger.info(f"reasoning content: {response.choices[0].message.reasoning_content}")
                ans = response.choices[0].message.content
                if ans:
                    return ans
            except APIStatusError:
                continue

    async def generate_image(self, prompt: str):
        api_key = self.get_api_key()
        for model in self.models:
            try:
                logger.info(f"use model {model}")
                response = await self._clients[api_key].images.generate(
                    model=model,
                    prompt=prompt
                )
                return response.data[0].url
            except APIStatusError:
                continue

chat_model: ChatModel = None
preprocess_model: ChatModel = None
image_model: ChatModel = None
search_model: ChatModel = None
gen_image_model: ChatModel = None

def load_models():
    config_file = get_plugin_config_file("models.json")
    if not config_file.exists():
        logger.error("models.json not found, creating default file")
        default = {
            "chat": {
                "api_keys": [],
                "models": []
            }
        }
        with config_file.open("w") as wf:
            json.dump(default, wf, indent=4)
        return
    with config_file.open() as rf:
        config = json.load(rf)
    global chat_model, preprocess_model, image_model, search_model, gen_image_model
    chat_model = ChatModel(**config["chat"])
    if "preprocess" in config:
        preprocess_model = ChatModel(**config["preprocess"])
    else:
        preprocess_model = chat_model
    if "image" in config:
        image_model = ChatModel(**config["image"])
    if "search" in config:
        search_model = ChatModel(**config["search"])
    if "gen-image" in config:
        gen_image_model = ChatModel(**config["gen-image"])

async def get_preprocess_info(dumped_messages: list[dict[str, str]], keywords: list[str]) -> dict[str | list[str]]:
    if not preprocess_model:
        return

    with open("src/preprocess-prompt.md") as rf:
        messages = [{
            "role": "system",
            "content": rf.read()
        }]
    messages.append({
        "role": "system",
        "content": ("关键词：" + "、".join(keywords)) if keywords else "目前无群聊关键词"
    })
    messages.extend(dumped_messages)

    retry = 3
    while retry:
        try:
            return json.loads(await preprocess_model.chat(messages))
        except Exception:
            retry -= 1
            if retry:
                logger.warning("get preprocess info failed, retrying")

async def get_image_description(image_data: str, prompt: str) -> str:
    if not image_model:
        return

    messages = [{
        "role": "system",
        "content": "请结合描述提示词根据图片内容进行描述，描述要尽可能详细，一百字以上"
    }, {
        "role": "user",
        "content": [{
            "type": "text",
            "text": prompt
        }, {
            "type": "image_url",
            "image_url": {"url": image_data}
        }]
    }]

    return await image_model.chat(messages)

async def search(query: str) -> str:
    if not search_model:
        return

    messages = [{
        "role": "system",
        "content": "请进行充分的网络检索，全面但是简洁的回答我的问题，回答字数不要超过200"
    }, {
        "role": "user",
        "content": query
    }]

    return await search_model.chat(messages)

async def generate_image(prompt: str) -> str:
    if not gen_image_model:
        return

    return await gen_image_model.generate_image(prompt)

async def chat(
        dumped_messages: list[dict[str, str]],
        prompt: str,
        image_desc: list[tuple[int, str]],
        search_info: list[str]
    ) -> list[str | dict[str, str]]:
    if not chat_model:
        raise ValueError("chat model not loaded")

    messages = [{
        "role": "system",
        "content": i
    } for i in chat_prompt]
    if image_desc:
        messages.extend([{
            "role": "system",
            "content": f"图片{id}的内容：{desc}"
        } for id, desc in image_desc])
    if search_info:
        messages.append({
            "role": "system",
            "content": "这是一些补充信息，你可以进行参考：\n" + "\n".join(search_info)
        })
    messages.append({
        "role": "system",
        "content": f"当前时间：{time.strftime('%Y-%m-%d %H:%M:%S')}"
    })
    if prompt:
        messages.append({
            "role": "user",
            "content": prompt
        })
    messages.extend(dumped_messages)

    return json.loads(await chat_model.chat(messages))
