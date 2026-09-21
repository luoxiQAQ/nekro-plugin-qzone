import sys

# nekro 的热重载只丢弃顶层模块，子模块会留在 sys.modules 里继续跑旧代码；
# 清掉自己名下的子模块，/api/plugins/reload 才能真的加载到最新代码。
for _stale in [name for name in sys.modules if name.startswith(f"{__name__}.")]:
    sys.modules.pop(_stale, None)

from .plugin import plugin

from . import main  # noqa: F401

__all__ = ["plugin"]