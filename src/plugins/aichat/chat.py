import json
from datetime import datetime
from typing import cast

import httpx
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.prompts import ChatPromptTemplate
from langchain.tools import BaseTool, tool
from langchain_openai import ChatOpenAI
from nonebot import get_plugin_config
from pydantic import BaseModel

from .config import Config
from .tools import ToolReturn, generate_image, search, web_scraper

PROMPT_PATH = "./src/resources/prompts"

plugin_config = get_plugin_config(Config)


class PredictResponse(BaseModel):
    reason: str
    desire: int


llm = ChatOpenAI(
    api_key=plugin_config.chat_api_key,
    base_url=plugin_config.chat_base_url,
    model=plugin_config.chat_model,
    temperature=0.3,
)
structured_llm = llm.with_structured_output(PredictResponse, method="json_mode")
thinking_llm: ChatOpenAI | None = None


async def get_predict(bot_name: str, group_name: str, history: list[str]):
    with open(f"{PROMPT_PATH}/group-predict-system.md", encoding="utf-8") as rf:
        system_prompt_template = rf.read()

    prompt = ChatPromptTemplate(
        [
            ("system", system_prompt_template),
            ("human", "群聊历史消息：\n\n{history}"),
        ]
    )

    return cast(
        PredictResponse,
        await (prompt | structured_llm).ainvoke(
            {
                "bot_name": bot_name,
                "group_name": group_name,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "history": "\n\n".join(history),
            }
        ),
    )


async def get_image(prompt: str):
    if not plugin_config.image_api_key:
        return None
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.stability.ai/v2beta/stable-image/generate/{plugin_config.image_model}",
            headers={
                "accept": "image/*",
                "authorization": f"Bearer {plugin_config.image_api_key}",
            },
            files={"none": ""},
            data={
                "prompt": prompt,
            },
            timeout=30,
        )
    if response.status_code == 200:
        return response.content


def thinking(content: str) -> str:
    if not plugin_config.thinking_model:
        return "思考功能未启用"
    global thinking_llm
    if not thinking_llm:
        thinking_llm = ChatOpenAI(
            api_key=plugin_config.chat_api_key,
            base_url=plugin_config.chat_base_url,
            model=plugin_config.thinking_model,
            temperature=0.3,
        )
    return thinking_llm.invoke(content).text()


async def group_chat(
    bot_name: str, group_name: str, cf_prompt: str, history: list[str]
) -> list[str] | ToolReturn:
    with open(f"{PROMPT_PATH}/group-chat-system.md", encoding="utf-8") as rf:
        system_prompt_template = rf.read()

    prompt = ChatPromptTemplate(
        [
            ("system", system_prompt_template),
            ("human", "{cf_prompt}\n\n群聊历史消息：\n\n{history}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    )

    tools: list[BaseTool] = [search, web_scraper]
    if plugin_config.image_api_key:
        tools.append(generate_image)
    if plugin_config.thinking_model:
        tools.append(
            tool(
                thinking,
                description="深度思考给定的问题，返回思考结果，可用于数学、逻辑问题等",
            )
        )

    agent_executor = AgentExecutor(
        agent=create_tool_calling_agent(llm, tools, prompt),
        tools=tools,
        max_iterations=8,
        verbose=True,
    )

    try:
        response = await agent_executor.ainvoke(
            {
                "bot_name": bot_name,
                "group_name": group_name,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "cf_prompt": cf_prompt,
                "history": "\n\n".join(history),
            },
        )
        return json.loads(response["output"])
    except ToolReturn as e:
        return e
