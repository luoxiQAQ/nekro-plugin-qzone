import importlib
import sys

# nekro 的热重载只丢弃顶层模块，子模块会留在 sys.modules 里继续跑旧代码；
# 清掉自己名下的子模块，/api/plugins/reload 才能真的加载到最新代码。
for _stale in [name for name in sys.modules if name.startswith(f"{__name__}.")]:
    sys.modules.pop(_stale, None)


def _ensure_dependency(package_spec: str, import_name: str) -> None:
    """确保第三方依赖可用。

    优先复用当前环境里已有的版本（NA 主环境里 croniter 本来就是硬依赖），确实缺失时
    才交给 NA 的动态包安装，装到 data/plugins/.dynamic_packages。这样不会重复下载，
    也不会因为 NA 把 .dynamic_packages 插到 sys.path 最前面而遮蔽主环境的版本。
    老版本 NA（2025-09 之前）没有 dynamic_import_pkg，此时直接返回，让缺依赖的场景
    照常抛 ModuleNotFoundError，而不是把加载流程打断成别的错误。
    """
    try:
        importlib.import_module(import_name)
        return
    except ImportError:
        pass

    try:
        from nekro_agent.api.plugin import dynamic_import_pkg
    except ImportError:
        return

    dynamic_import_pkg(package_spec, import_name=import_name)


# 声明本插件的第三方依赖：手动把插件放进 plugins 目录时，requirements.txt 不会被自动安装
for _package_spec, _import_name in (
    ("beautifulsoup4>=4.12.0", "bs4"),
    ("croniter>=2.0.0", "croniter"),
):
    _ensure_dependency(_package_spec, _import_name)

del _package_spec, _import_name

from .plugin import plugin

from . import main  # noqa: F401

__all__ = ["plugin"]
