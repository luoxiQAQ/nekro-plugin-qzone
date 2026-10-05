from __future__ import annotations

from pathlib import Path

from nekro_agent.api.message import send_image as api_send_image
from nekro_agent.api.message import send_text as api_send_text
from nekro_agent.schemas.agent_ctx import AgentCtx

from .config import PluginConfig
from .log import logger
from .model import Post
from .renderer import create_message_renderer


class Sender:
    def __init__(self, config: PluginConfig):
        self.cfg = config
        self.renderer = create_message_renderer(config)

    async def _ctx_for(self, chat_key: str) -> AgentCtx:
        return await AgentCtx.create_by_chat_key(chat_key, container_key=f"sandbox_{chat_key}")

    async def _send_image_file(self, chat_key: str, local_path: Path, ctx: AgentCtx) -> None:
        sandbox = await ctx.fs.mixed_forward_file(local_path, file_name=local_path.name)
        await api_send_image(chat_key, str(sandbox), ctx)

    async def send_post(self, chat_key: str, post: Post, message: str = "") -> None:
        try:
            ctx = await self._ctx_for(chat_key)
            if message:
                await api_send_text(chat_key, message, ctx)
            image_path = await self.renderer.render_post(post)
            if image_path:
                await self._send_image_file(chat_key, image_path, ctx)
            else:
                await api_send_text(chat_key, post.to_str(), ctx)
        except Exception as e:
            logger.error(f"发送说说失败（{chat_key}）：{e}")

    async def send_msg(self, chat_key: str, message: str) -> None:
        try:
            ctx = await self._ctx_for(chat_key)
            image_path = await self.renderer.render_text(message)
            if image_path:
                await self._send_image_file(chat_key, image_path, ctx)
            else:
                await api_send_text(chat_key, message, ctx)
        except Exception as e:
            logger.error(f"发送消息失败（{chat_key}）：{e}")

    @staticmethod
    async def _ensure_channel(chat_key: str) -> bool:
        """确保目标频道存在（不存在则补齐频道记录），失败时返回 False。"""
        try:
            from nekro_agent.models.db_chat_channel import DBChatChannel
            from nekro_agent.schemas.chat_message import ChatType

            if await DBChatChannel.get_or_none(chat_key=chat_key):
                return True
            adapter_key, _, channel_id = chat_key.partition("-")
            raw_channel_id = channel_id.split(":", 1)[-1]
            channel_type = (
                ChatType.GROUP if raw_channel_id.startswith("group_") else ChatType.PRIVATE
            )
            await DBChatChannel.get_or_create(
                adapter_key=adapter_key or "onebot_v11",
                channel_id=channel_id,
                channel_type=channel_type,
            )
            logger.info(f"已为通知补齐聊天频道: {chat_key}")
            return True
        except Exception as e:
            logger.warning(f"准备通知频道失败（{chat_key}）：{e}")
            return False

    def _notification_targets(self, account_id: str = "") -> list[str]:
        prefix = f"{account_id}:" if account_id else ""
        targets: list[str] = []
        if self.cfg.manage_group and self.cfg.manage_group.isdigit():
            targets.append(f"onebot_v11-{prefix}group_{self.cfg.manage_group}")
        for admin_id in self.cfg.admins_id:
            targets.append(f"onebot_v11-{prefix}private_{admin_id}")
        return targets

    async def send_admin_post(self, post: Post, message: str = "", account_id: str = "") -> None:
        for chat_key in self._notification_targets(account_id):
            if not await self._ensure_channel(chat_key):
                continue
            await self.send_post(chat_key, post, message=message)


    async def send_admin_msg(self, message: str, account_id: str = "") -> None:
        """向管理群/管理员发送纯文本通知"""
        for chat_key in self._notification_targets(account_id):
            if not await self._ensure_channel(chat_key):
                continue
            await self.send_msg(chat_key, message)

