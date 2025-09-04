# XeF4：多功能QQ机器人

XeF4 项目使用 `uv` 进行包管理，使用 `nonebot` 与 `langchain` 框架开发。目前机器人可用功能如下：

- AI 对话（支持提示词设定、图片生成和自定义工具）
- Minecraft 服务器连接（包含服务器信息查询、群服互通）
- 群聊互动（包含自动接龙、戳一戳等）
- ...

## 部署指南

### 1. 创建环境

```bash
uv sync
```

或使用 `pyvenv`：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 环境配置

根据 `.env.example` 中的示例配置文件，创建 `.env` 文件并填写必要的配置项。

### 3. 启动项目

```bash
uv run bot.py
```

或在虚拟环境中运行：

```bash
source .venv/bin/activate
python bot.py
```

### 4. 机器人配置

在 `nonebot` 配置文件夹的 `global` 目录中填写机器人启用的群聊、私聊，并完成其他配置。

> 机器人连接与其他相关配置请参考 [NoneBot 文档](https://nonebot.dev/docs/)
