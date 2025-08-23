import nonebot
from nonebot.adapters.minecraft import Adapter as MinecraftAdapter
from nonebot.adapters.onebot.v11 import Adapter as OnebotAdapter

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(OnebotAdapter)
driver.register_adapter(MinecraftAdapter)

nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
