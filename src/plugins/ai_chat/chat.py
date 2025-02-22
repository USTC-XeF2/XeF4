import json
import random
from openai import AsyncOpenAI, APIStatusError

from nonebot import logger
from nonebot_plugin_localstore import get_plugin_config_file

preprocess_prompt = [
    "下文是群聊中的一段消息，你需要结合这些信息来判断回复新消息的欲望程度及其信息",
    "新消息引用链是一个列表，其中第一项是你需要判断是否应回复的消息，后面的消息依次是新消息所引用的消息",
    """你的输出需要是json格式，包含以下字段：
- desire: 一个0-20的整数，表示对回答新消息的欲望程度
- reason: 选择这个回复欲望的详细原因
- search: 一个列表，如果用户的问题中包含询问时事性或是专业信息的内容，在字段中返回需要搜索的内容，否则保持为空
""",
    """示例回复：
{ "desire": 16, "reason": "用户问了我数学证明问题，并且有回复价值，因为...", "search": ["Python最新的版本是多少"] }
{ "desire": 5, "reason": "用户在和别人聊天，并且没有请求我的地方", "search": [] }""",
    "回复搜索问题时如果涉及到时间等内容应该根据聊天记录推断并进行具体的询问",
    "当新消息提及内容与你（例如你的名字）有关时，你可以适当提高欲望值",
    "当新消息存在疑问时，你可以适当提高欲望值；当新消息没有实际信息量时，你应该降低欲望值",
    "当历史消息中你的发言过于频繁时，你应该降低欲望值",
    "当用户让你刷屏或询问涉政涉黄请求时，你应该降低欲望值"
]

chat_prompt = [
    "下文是群聊中的一段消息，你需要结合这些信息来回复新消息",
    "新消息引用链是一个列表，其中第一项是你需要回复的消息，后面的消息依次是新消息所引用的消息",
    "你的回复需要是一个json格式列表，列表的每一项是一条消息，这些消息将会依次回复给用户",
    """列表中的每一条消息都是一个字典，需要包含以下字段：
- type: 消息的类型，可以是text, file, fstring
- content: 消息的内容，对于text类型是直接回复的消息，对于file类型是文件的内容，对于fstring类型是Python格式化字符串
- filename: 当type是file时，这个字段是文件名，否则可以省略""",
    "对于text类型的消息，可以直接以字符串的形式返回，不要超过30字，不要使用markdown记号，保持消息的短小",
    "对于fstring类型的消息，返回结果会自动解析{}中的内容，其中可以包含 re, math, random, time, datetime 五个模块的函数",
    """示例回复：
["你好，我是机器人", "请问有什么可以帮助你的吗？"]
[{"type":"fstring","content":"现在的时间是{time.strftime('%H点%M')}"}]
[{"type":"fstring","content":"114514*1919810的结果是{114514*1919810}"}, {"type":"fstring","content":"这个结果比10^11{'大' if 114514*1919810 > 10**11 else '小'}"}]
["这是你需要的txt文件", {"type":"file","content":"...","filename":"example.txt"}]""",
    "尽量把自己拟人化，删去问候或鼓励等机器人的常见回答方式，对话不用提到对方名称",
    "回答内容除非过多，否则尽量简明扼要回答，回答后不需要再次提问",
    "其他用户都是真人，回答尽量模仿其他用户，不要显得格格不入，不要模仿你之前的说话风格",
    "当用户询问数学相关的任何问题时，请尽量结合fstring完成回答",
    "回答过程中注意结合历史消息，但是回复内容要针对于新消息（而非新消息的引用消息）"
]

class ChatModel:
    _clients = dict[str, AsyncOpenAI]()
    def __init__(self, api_keys: list[str], models: list[str], base_url: str = None):
        self.api_keys = api_keys
        self.base_url = base_url
        self.models = models

    async def chat(self, messages: list[dict[str]]):
        api_key = random.choice(self.api_keys)
        if api_key not in self._clients:
            masked_api_key = api_key[:8] + "*" * 10 + api_key[-4:]
            logger.info(f"create client for api key {masked_api_key}")
            type(self)._clients[api_key] = AsyncOpenAI(api_key=api_key, base_url=self.base_url)
        for model in self.models:
            try:
                logger.info(f"use model {model}")
                response = await self._clients[api_key].chat.completions.create(
                    model=model,
                    messages=messages
                )
                ans = response.choices[0].message.content
                if ans:
                    return ans
            except APIStatusError as e:
                print(e, e.args)
                continue

chat_model: ChatModel = None
preprocess_model: ChatModel = None
search_model: ChatModel = None

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
    global chat_model, preprocess_model, search_model
    chat_model = ChatModel(**config["chat"])
    if "preprocess" in config:
        preprocess_model = ChatModel(**config["preprocess"])
    else:
        preprocess_model = chat_model
    if "search" in config:
        search_model = ChatModel(**config["search"])

async def get_preprocess_info(dumped_messages: list[dict[str, str]]) -> dict[str]:
    if not preprocess_model:
        raise ValueError("preprocess model not loaded")

    messages = [{
        "role": "system",
        "content": i
    } for i in preprocess_prompt]
    messages.extend(dumped_messages)

    for _ in range(3):
        try:
            return json.loads(await preprocess_model.chat(messages))
        except Exception:
            logger.warning("get preprocess info failed, retrying")

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

async def chat(dumped_messages: list[dict[str, str]], search_info: list[str]) -> list[str | dict[str, str]]:
    if not chat_model:
        raise ValueError("chat model not loaded")

    messages = [{
        "role": "system",
        "content": i
    } for i in chat_prompt]
    if search_info:
        messages.append({
            "role": "system",
            "content": "这是一些补充信息，你可以进行参考：\n" + "\n".join(search_info)
        })
    messages.extend(dumped_messages)

    for _ in range(3):
        try:
            return json.loads(await chat_model.chat(messages))
        except Exception:
            logger.warning("get chat response failed, retrying")
