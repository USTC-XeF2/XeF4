from ddgs import DDGS
from langchain.tools import tool
from langchain_community.document_loaders import WebBaseLoader


class ToolReturn(Exception):
    def __init__(self, type: str, result):
        self.type = type
        self.result = result


@tool
def generate_image(prompt: str) -> str:
    """根据提示词生成图像并直接发送给用户

    Args:
        prompt: 生成图像的英文提示词，100字以上
    """
    raise ToolReturn("image", prompt)


@tool
def search(query: str) -> str:
    """搜索时效性或相关领域的信息，返回搜索引擎给出的若干个结果

    Args:
        query: 发送给搜索引擎的字符串
    """

    with DDGS() as ddgs:
        ddgs_gen = ddgs.text(
            query,
            region="zh-cn",
            timelimit="y",
            max_results=5,
        )
        if ddgs_gen:
            return "\n".join(r["body"] for r in ddgs_gen)
    return "未找到相关的搜索结果"


@tool
def web_scraper(url: str) -> str:
    """一个可以从指定URL抓取网页内容的工具

    Args:
        url: 要抓取的网页URL
    """
    try:
        loader = WebBaseLoader(url)
        docs = loader.load()
        if not docs:
            return "从该URL找不到任何内容。"

        return docs[0].page_content
    except Exception:
        return "抓取网页时发生错误，无法获取内容。"
