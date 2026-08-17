from __future__ import annotations

from .config import PluginConfig
from .db import PostDB
from .model import Post
from .sender import Sender
from .service import PostService


class CampusWall:
    def __init__(
        self,
        config: PluginConfig,
        service: PostService,
        db: PostDB,
        sender: Sender,
    ):
        self.cfg = config
        self.service = service
        self.db = db
        self.sender = sender

    async def contribute(
        self,
        *,
        chat_key: str,
        user_id: str,
        username: str,
        gin: int,
        text: str,
        images: list[str],
        anon: bool = False,
    ) -> str:
        post = Post(
            uin=int(user_id) if user_id.isdigit() else 0,
            name=username,
            gin=gin,
            text=text,
            images=images,
            anon=anon,
            status="pending",
        )
        await self.db.save(post)
        await self.sender.send_post(chat_key, post, message="已投，等待审核...")
        await self.sender.send_admin_post(post, message=f"收到新投稿#{post.id}")
        return f"已投稿#{post.id}，等待审核..."

    async def delete(self, *, user_id: str, post_id: int, reason: str = "") -> str:
        post = await self.db.get(post_id)
        if not post or not post.id:
            return f"稿件#{post_id}不存在"
        if not user_id.isdigit() or post.uin != int(user_id):
            return "你只能撤回自己的稿件"
        await self.db.delete(post.id)
        msg = f"稿件#{post.id}已撤回"
        if reason:
            msg += f"\n理由：{reason}"
        await self.sender.send_admin_post(post, message=msg)
        return msg

    async def view(self, *, chat_key: str, post_id: int) -> str:
        post = await self.db.get(post_id)
        if not post:
            return f"稿件#{post_id}不存在"
        await self.sender.send_post(chat_key, post)
        return f"稿件#{post.id}"

    async def approve(self, *, chat_key: str, post_id: int) -> str:
        post = await self.db.get(post_id)
        if not post:
            return f"稿件#{post_id}不存在"
        if post.status == "approved":
            return f"稿件#{post.id}已通过，请勿重复通过"
        if self.cfg.show_name:
            post.text = f"【来自 {post.show_name} 的投稿】\n\n{post.text}"
        try:
            post_ = await self.service.publish_post(post=post)
        except Exception as e:
            return str(e)
        await self.sender.send_post(chat_key, post_, message=f"已发布说说#{post.id}")
        await self.sender.send_user_post(post_, message=f"您的投稿#{post.id}已通过")
        return f"已通过稿件#{post.id}并发布"

    async def reject(self, *, chat_key: str, post_id: int, reason: str = "") -> str:
        post = await self.db.get(post_id)
        if not post:
            return f"稿件#{post_id}不存在"
        if post.status == "rejected":
            return f"稿件#{post.id}已拒绝，请勿重复拒绝"
        if post.status == "approved":
            return f"稿件#{post.id}已发布，无法拒绝"
        post.status = "rejected"
        if reason:
            post.extra_text = reason
        await self.db.save(post)
        msg = f"已拒绝稿件#{post.id}"
        if reason:
            msg += f"\n理由：{reason}"
        user_msg = f"您的投稿#{post.id}未通过"
        if reason:
            user_msg += f"\n理由：{reason}"
        await self.sender.send_user_post(post, message=user_msg)
        return msg