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

    def _notification_targets(self) -> list[str]:
        targets: list[str] = []
        if self.cfg.manage_group and self.cfg.manage_group.isdigit():
            targets.append(f"onebot_v11-group_{self.cfg.manage_group}")
        for admin_id in self.cfg.admins_id:
            targets.append(f"onebot_v11-private_{admin_id}")
        return targets

    async def send_admin_post(self, post: Post, message: str = "") -> None:
        for chat_key in self._notification_targets():
            await self.send_post(chat_key, post, message=message)

    async def send_user_post(self, post: Post, message: str = "") -> None:
        if post.gin:
            await self.send_post(f"onebot_v11-group_{post.gin}", post, message=message)
        elif post.uin:
            await self.send_post(f"onebot_v11-private_{post.uin}", post, message=message)