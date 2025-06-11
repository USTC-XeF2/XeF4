import json
import time
from openai import AsyncOpenAI, APIStatusError

from nonebot import logger
from nonebot_plugin_localstore import get_plugin_config_file

chat_prompt = [
    "下文是群聊中的一段消息，你需要结合这些信息来回复新消息",
    "新消息引用链是一个列表，其中第一项是你需要回复的消息，后面的消息依次是新消息所引用的消息",
    "你的回复需要是一个json格式列表，列表的每一项是一条消息，这些消息将会依次发送到群聊中",
    """列表中的每一条消息都是一个字典，需要包含以下字段：
- type: 消息的类型，可以是text, image, file
- content: 消息的内容，对于text类型是直接回复的消息，对于image类型是图片描述，对于file类型是文件的内容
- filename: 当type是file时，这个字段是文件名，否则可以省略""",
    "对于text类型的消息，可以直接以字符串的形式返回，不要使用markdown记号（如**加粗或```代码块等）",
    "对于image类型的消息，图片描述要尽可能详细，一百字以上",
    """示例回复：
["你好，我是机器人", "请问有什么可以帮助你的吗？"]
[{"type":"image","content":"..."}, "你要的关于小猫睡觉的图片画好了"]
["这是你需要的txt文件", {"type":"file","content":"...","filename":"example.txt"}]""",
    "删去问候或鼓励等机器人的常见回答方式，对话不用提到对方名称，回答后不需要再次提问",
    "尽量把自己拟人化，不要过分增加设定，可以根据上下文使用其他群成员的发言方式增强融合感",
    "请确保你回答的消息都是真实可信的，不要编造虚假信息",
    "回答过程中注意结合历史消息，但是回复内容要针对于新消息（而非新消息的引用消息）",
    "回答消息时如果提到图片，不需要提及图片编号信息",
    "当群成员向你发起生成图片请求时，请直接使用image进行回答，会根据描述自动生成图片",
    "回答内容如果过长可以适当分条回答，保持每条text消息尽量简短没有多余信息，不要超过3条消息",
    "较长但连贯的回答内容可以在同一条内换行而不必分条，如果是简短的回复末尾不需要加“。”",
    "如果你认为不需要或不适合回答，应该直接返回空列表",
    "当群成员询问涉政涉黄请求时，你应该拒绝回答"
]

class ChatModel:
    _providers = dict[str, dict[str, str]]()
    _clients = dict[str, AsyncOpenAI]()
    def __init__(self, choices: list[tuple[str, str]]):
        self.choices = choices

    @classmethod
    def set_providers(cls, providers: dict[str, dict[str]]):
        cls._providers = providers
        cls._clients = {}

    @classmethod
    def get_client(cls, provider_name: str):
        if provider_name not in cls._clients:
            provider = cls._providers.get(provider_name)
            if not provider:
                logger.error(f"provider {provider_name} not found")
                return
            logger.info(f"create client for {provider_name}")
            cls._clients[provider_name] = AsyncOpenAI(
                api_key=provider["api_key"],
                base_url=provider.get("base_url", None)
            )
        return cls._clients[provider_name]

    def iter_client(self):
        for provider_name, model in self.choices:
            client = self.get_client(provider_name)
            if client:
                logger.info(f"use provider {provider_name!r} for model {model!r}")
                yield (client, model)

    async def chat(self, messages: list[dict[str]]):
        for client, model in self.iter_client():
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages
                )
                if hasattr(response.choices[0].message, "reasoning_content"):
                    logger.info(f"reasoning content: {response.choices[0].message.reasoning_content}")
                ans = response.choices[0].message.content
                if ans:
                    return ans.removeprefix("```json").removesuffix("```").strip()
            except APIStatusError:
                continue

chat_model: ChatModel = None
preprocess_model: ChatModel = None
image_model: ChatModel = None
think_model: ChatModel = None
search_model: ChatModel = None
gen_image_model: ChatModel = None

def load_models():
    config_file = get_plugin_config_file("models.json")
    if not config_file.exists():
        logger.error("models.json not found, creating default file")
        default = {
            "providers": {
                "name": {
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "your_api_key"
                }
            },
            "preference": {
                "chat": [
                    ["provider-name", "model"]
                ]
            }
        }
        with config_file.open("w") as wf:
            json.dump(default, wf, indent=4)
        return
    with config_file.open() as rf:
        config: dict[str, dict[str]] = json.load(rf)
    ChatModel.set_providers(config["providers"])
    preference = config["preference"]
    global chat_model, preprocess_model, image_model, think_model, search_model, gen_image_model
    chat_model = ChatModel(preference["chat"])
    if "preprocess" in preference:
        preprocess_model = ChatModel(preference["preprocess"])
    else:
        preprocess_model = chat_model
    if "image" in preference:
        image_model = ChatModel(preference["image"])
    if "think" in preference:
        think_model = ChatModel(preference["think"])
    if "search" in preference:
        search_model = ChatModel(preference["search"])
    if "gen-image" in preference:
        gen_image_model = ChatModel(preference["gen-image"])

async def get_preprocess_info(dumped_messages: list[dict[str, str]]) -> dict[str | list[str]]:
    if not preprocess_model:
        return

    with open("src/preprocess-prompt.md") as rf:
        messages = [{
            "role": "system",
            "content": rf.read()
        }]
    messages.extend(dumped_messages)

    retry = 3
    while retry:
        try:
            return json.loads(await preprocess_model.chat(messages))
        except Exception:
            retry -= 1
            if retry:
                logger.warning("get preprocess info failed, retrying")

async def get_image_description(image_data: str, prompt: str):
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

async def search(query: str):
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

async def generate_image(prompt: str):
    if not gen_image_model:
        return

    for client, model in gen_image_model.iter_client():
        try:
            response = await client.images.generate(
                model=model,
                prompt=prompt
            )
            return response.data[0].url
        except APIStatusError:
            continue

async def chat(
        dumped_messages: list[dict[str, str]],
        prompt: str,
        image_desc: list[tuple[int, str]],
        search_info: list[str],
        think: bool
    ) -> list[str | dict[str, str]]:
    if not chat_model:
        raise ValueError("chat model not loaded")

    messages = []
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

    think_content = None
    if think and think_model:
        logger.info("thinking...")
        think_content = await think_model.chat(messages + dumped_messages)

    messages = [{
        "role": "system",
        "content": i
    } for i in chat_prompt] + messages
    if prompt:
        messages.append({
            "role": "user",
            "content": prompt
        })
    if think_content:
        messages.append({
            "role": "user",
            "content": f"深度思考结果：\n{think_content}"
        })
    messages.extend(dumped_messages)

    try:
        return json.loads(await chat_model.chat(messages))
    except Exception as e:
        logger.error(f"chat failed: {e.args[0]}")
        return []
