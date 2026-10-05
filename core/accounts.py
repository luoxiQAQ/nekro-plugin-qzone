from __future__ import annotations

from dataclasses import dataclass

from .config import PluginConfig
from .log import logger
from .qzone import QzoneAPI, QzoneSession


@dataclass(frozen=True)
class AccountSpec:
    """一个 QQ 账号实例（来自框架的多账号配置）。"""

    id: str
    qq: str
    label: str = ""

    @property
    def display(self) -> str:
        if self.label:
            return f"{self.label}({self.qq})" if self.qq else self.label
        return self.qq or self.id or "默认账号"


def list_accounts() -> list[AccountSpec]:
    """列出框架中配置的 QQ 账号实例；无多账号配置时返回单个空实例（单账号兼容）。"""
    try:
        from nekro_agent.adapters.onebot_v11.core.bot import get_bot_instances
    except Exception:
        return [AccountSpec(id="", qq="", label="")]
    try:
        specs = get_bot_instances()
    except Exception as e:
        logger.warning(f"获取多账号实例列表失败，按单账号模式运行：{e}")
        return [AccountSpec(id="", qq="", label="")]
    accounts = [
        AccountSpec(
            id=str(spec.id or spec.qq),
            qq=str(spec.qq),
            label=str(getattr(spec, "display_name", "") or ""),
        )
        for spec in specs
        if getattr(spec, "enabled", True)
    ]
    return accounts or [AccountSpec(id="", qq="", label="")]


def resolve_account_id(chat_key: str) -> str:
    """从会话标识解析所属账号实例标识；无账号前缀（历史会话）时返回空串。"""
    if not chat_key:
        return ""
    try:
        from nekro_agent.models.db_chat_channel import extract_account_scope

        return extract_account_scope(chat_key) or ""
    except Exception:
        return ""


async def get_chat_persona(chat_key: str) -> str:
    """获取频道生效的人设内容（会话绑定 > 账号默认 > 全局默认 > 内置）。"""
    if not chat_key:
        return ""
    try:
        from nekro_agent.models.db_chat_channel import DBChatChannel

        channel = await DBChatChannel.get_channel(chat_key)
        preset = await channel.get_preset()
        return str(getattr(preset, "content", "") or "")
    except Exception as e:
        logger.warning(f"获取频道人设失败（{chat_key}）：{e}")
        return ""


async def get_account_persona(account_id: str) -> str:
    """获取账号默认人设内容（ACCOUNT_DEFAULT_PRESET_IDS，回退全局默认）；未配置时返回空串。"""
    try:
        from nekro_agent.core.config import config as core_config
        from nekro_agent.models.db_preset import DBPreset
        from nekro_agent.services.preset_service import get_account_default_preset_id
    except Exception:
        return ""

    preset_id = get_account_default_preset_id(account_id) if account_id else None
    if not preset_id:
        preset_id = getattr(core_config, "AI_CHAT_DEFAULT_PRESET_ID", None)
    if not preset_id:
        return ""
    try:
        preset = await DBPreset.get_or_none(id=preset_id)
    except Exception as e:
        logger.warning(f"获取账号默认人设失败（{account_id or '默认'}）：{e}")
        return ""
    return str(getattr(preset, "content", "") or "")


class AccountRegistry:
    """按账号实例缓存 QQ 空间登录态与接口客户端。"""

    def __init__(self, config: PluginConfig):
        self.cfg = config
        self._entries: dict[str, tuple[QzoneSession, QzoneAPI]] = {}

    def resolve(self, account_id: str = "") -> tuple[QzoneSession, QzoneAPI]:
        key = account_id or ""
        entry = self._entries.get(key)
        if entry is None:
            session = QzoneSession(self.cfg, account_id=key)
            entry = (session, QzoneAPI(session, self.cfg))
            self._entries[key] = entry
        return entry

    async def close(self) -> None:
        for _session, api in list(self._entries.values()):
            try:
                await api.close()
            except Exception as e:
                logger.warning(f"关闭 QQ 空间接口客户端失败：{e}")
        self._entries.clear()
