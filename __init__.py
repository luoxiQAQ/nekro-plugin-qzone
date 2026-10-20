import sys

# nekro 的热重载只丢弃顶层模块，子模块会留在 sys.modules 里继续跑旧代码；
# 清掉自己名下的子模块，/api/plugins/reload 才能真的加载到最新代码。
for _stale in [name for name in sys.modules if name.startswith(f"{__name__}.")]:
    sys.modules.pop(_stale, None)

# 声明并安装本插件的第三方依赖。
# NekroAgent 会把它们装到 data/plugins/.dynamic_packages 并加入 sys.path，
# 这样即使插件是手动放进 packages 目录（没有走依赖安装流程）也能正常加载。
try:
    from nekro_agent.api.plugin import dynamic_import_pkg

    for _package_spec, _import_name in (
        ("beautifulsoup4", "bs4"),
        ("croniter", "croniter"),
    ):
        _module = dynamic_import_pkg(_package_spec, import_name=_import_name)
        sys.modules.setdefault(_import_name, _module)
except Exception as _error:  # noqa: BLE001
    raise RuntimeError(
        "QQ空间插件依赖安装失败（beautifulsoup4 / croniter）。"
        "请检查网络，或确认配置里的 DYNAMIC_PLUGIN_INSTALL_MIRROR / 动态包安装代理可用。"
        f"原始错误：{_error}"
    ) from _error

from .plugin import plugin

from . import main  # noqa: F401

__all__ = ["plugin"]
