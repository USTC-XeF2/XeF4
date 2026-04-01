import nonebot
from nonebot.adapters.minecraft import Adapter as MinecraftAdapter
from nonebot.adapters.onebot.v11 import Adapter as OnebotAdapter

nonebot.init(
    driver="~fastapi+~websockets",
    alconna_use_command_start=True,
    localstore_use_cwd=True,
    session_config_enable_param=True,
)

driver = nonebot.get_driver()
driver.register_adapter(OnebotAdapter)
driver.register_adapter(MinecraftAdapter)

nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
