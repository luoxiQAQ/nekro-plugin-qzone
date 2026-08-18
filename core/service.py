import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

from .config import PluginConfig
from .log import logger
from .db import PostDB
from .llm_action import LLMAction
from .model import Comment, Post
from .qzone import QzoneAPI, QzoneParser, QzoneSession
from .qzone.constants import (
    HTTP_STATUS_FORBIDDEN,
    QZONE_CODE_LOGIN_EXPIRED,
    QZONE_CODE_PERMISSION_DENIED,
    QZONE_CODE_PERMISSION_DENIED_LEGACY,
    QZONE_CODE_UNKNOWN,
    QZONE_INTERNAL_HTTP_STATUS_KEY,
    QZONE_INTERNAL_META_KEY,
    QZONE_MSG_EMPTY_RESPONSE,
    QZONE_MSG_INVALID_RESPONSE,
    QZONE_MSG_JSON_PARSE_ERROR,
    QZONE_MSG_NON_OBJECT_RESPONSE,
    QZONE_MSG_PERMISSION_DENIED,
)


try:
    from ...nekro_plugin_semantic_sticker.agent_tools import get_service as _get_sticker_service
    from ...nekro_plugin_semantic_sticker.models import ReplyMode as _StickerReplyMode
    from ...nekro_plugin_semantic_sticker.models import UsageContext as _StickerUsageContext
    _STICKER_INTEGRATION_AVAILABLE = True
except Exception:  # pragma: no cover - semantic sticker plugin unavailable
    _get_sticker_service = None
    _StickerReplyMode = None
    _StickerUsageContext = None
    _STICKER_INTEGRATION_AVAILABLE = False

if _STICKER_INTEGRATION_AVAILABLE:
    logger.info("Semantic sticker integration enabled for Qzone publishing")


class PostService:
    """
    Application Service 层
    """

    def __init__(
        self,
        qzone: QzoneAPI,
        session: QzoneSession,
        db: PostDB,
        llm: LLMAction,
        config: PluginConfig,
    ):
        self.qzone = qzone
        self.session = session
        self.db = db
        self.llm = llm
        self.cfg = config

    # ============================================================
    # 业务接口
    # ============================================================

    async def query_feeds(
        self,
        *,
        target_id: str | None = None,
        pos: int = 0,
        num: int = 1,
        with_detail: bool = False,
        no_self: bool = False,
        no_commented: bool = False,
    ) -> list[Post]:
        if target_id:
            resp = await self.qzone.get_feeds(target_id, pos=pos, num=num)
            if not resp.ok:
                raise RuntimeError(self._map_feed_error(resp, target_id=target_id))
            msglist = resp.data.get("msglist") or []
            if not msglist:
                logger.info(f"QQ {target_id} 暂无可见说说（非错误，返回空列表）")
                return []
            posts: list[Post] = QzoneParser.parse_feeds(msglist)

        else:
            resp = await self.qzone.get_recent_feeds()
            if not resp.ok:
                raise RuntimeError(self._map_feed_error(resp))
            posts: list[Post] = QzoneParser.parse_recent_feeds(resp.data)[
                pos : pos + num
            ]
            if not posts:
                raise RuntimeError("动态流暂无可见说说")

        if no_self:
            uin = await self.session.get_uin()
            posts = [p for p in posts if p.uin != uin]

        if with_detail:
            posts = await self._fill_post_detail(posts)
            if not posts:
                raise RuntimeError("获取详情后无有效说说")

        if no_commented:
            posts = await self._filter_not_commented(posts)

        for post in posts:
            await self.db.save(post)

        return posts

    @staticmethod
    def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
        return any(k in text for k in keywords)

    def _map_feed_error(self, resp, *, target_id: str | None = None) -> str:
        message = str(resp.message or "").strip()
        lower_message = message.lower()
        code = resp.code
        http_status = self._extract_http_status(resp.raw)

        permission_keywords = (
            "无权限",
            "权限",
            "私密",
            "不可见",
            "拒绝访问",
            "受限",
            "forbidden",
            QZONE_MSG_PERMISSION_DENIED,
            "access denied",
        )
        login_keywords = ("登录", "失效", "skey", "g_tk", "cookie", "expired")

        if code == QZONE_CODE_LOGIN_EXPIRED or self._contains_any(
            lower_message, login_keywords
        ):
            return "登录状态失效，请重新登录后重试"

        if (
            code in (QZONE_CODE_PERMISSION_DENIED, QZONE_CODE_PERMISSION_DENIED_LEGACY)
            or http_status == HTTP_STATUS_FORBIDDEN
            or self._contains_any(lower_message, permission_keywords)
        ):
            if target_id:
                return f"无权限查看 QQ {target_id} 的说说"
            return "无权限访问动态流"

        if code == QZONE_CODE_UNKNOWN and message == QZONE_MSG_EMPTY_RESPONSE:
            if target_id:
                return f"无权限查看 QQ {target_id} 的说说（接口返回空响应）"
            return "动态接口返回空响应，请稍后重试"

        if code == QZONE_CODE_UNKNOWN and message in (
            QZONE_MSG_INVALID_RESPONSE,
            QZONE_MSG_JSON_PARSE_ERROR,
            QZONE_MSG_NON_OBJECT_RESPONSE,
        ):
            return "接口响应格式异常，请稍后重试"

        if message:
            return f"查询说说失败：{message}"
        return f"查询说说失败：code={code}"

    @staticmethod
    def _extract_http_status(raw: dict[str, Any]) -> int | None:
        meta = raw.get(QZONE_INTERNAL_META_KEY)
        if not isinstance(meta, dict):
            return None
        status = meta.get(QZONE_INTERNAL_HTTP_STATUS_KEY)
        return status if isinstance(status, int) else None

    @staticmethod
    def _has_comment_from_uin(post: Post, uin: int) -> bool:
        return any(comment.uin == uin for comment in post.comments)

    async def _has_saved_self_comment(self, post: Post, uin: int) -> bool:
        if not post.tid:
            return False
        saved_post = await self.db.get(post.tid, key="tid")
        return bool(saved_post and self._has_comment_from_uin(saved_post, uin))

    async def _fill_post_detail(self, posts: list[Post]) -> list[Post]:
        result: list[Post] = []

        for post in posts:
            resp = await self.qzone.get_detail(post)
            if not resp.ok or not resp.data:
                logger.warning(f"获取详情失败：{resp.data}")
                continue

            parsed = QzoneParser.parse_feeds([resp.data])
            if not parsed:
                logger.warning(f"解析详情失败：{resp.data}")
                continue

            result.append(parsed[0])

        return result

    async def _filter_not_commented(self, posts: list[Post]) -> list[Post]:
        result: list[Post] = []
        uin = await self.session.get_uin()

        for post in posts:
            if self._has_comment_from_uin(post, uin):
                continue
            if await self._has_saved_self_comment(post, uin):
                continue

            # 如果已经有 comments，说明是 detail post
            if not post.comments:
                resp = await self.qzone.get_detail(post)
                if not resp.ok or not resp.data:
                    continue
                parsed = QzoneParser.parse_feeds([resp.data])
                if not parsed:
                    continue
                post = parsed[0]

            if self._has_comment_from_uin(post, uin):
                continue

            result.append(post)

        return result

    # ==================== 对外接口 ========================

    async def view_visitor(self) -> str:
        """查看访客"""
        resp = await self.qzone.get_visitor()
        if not resp.ok:
            raise RuntimeError(f"获取访客异常：{resp.data}")
        if not resp.data:
            raise RuntimeError("无访客记录")
        return QzoneParser.parse_visitors(resp.data)

    async def like_posts(self, post: Post):
        """点赞帖子"""
        if not post.tid:
            raise ValueError("帖子 tid 为空")
        await self.qzone.like(post)
        logger.info(f"已点赞 → {post.name}")

    async def comment_posts(
        self, post: Post, chat_key: str = ""
    ):
        """评论帖子"""
        if not post.tid:
            raise ValueError("帖子 tid 为空")

        content = await self.llm.generate_comment(post, chat_key=chat_key)
        if not content:
            raise ValueError("生成评论内容为空")

        await self.qzone.comment(post, content)

        uin = await self.session.get_uin()
        name = await self.session.get_nickname()
        post.comments.append(
            Comment(
                uin=uin,
                nickname=name,
                content=content,
                create_time=int(time.time()),
                tid=0,
                parent_tid=None,
            )
        )
        await self.db.save(post)
        logger.info(f"评论 → {post.name}")

    async def _attach_semantic_sticker(self, post: Post) -> None:
        """Attach one semantically matched sticker to the feed when enabled."""
        if not self.cfg.enable_post_image or not _STICKER_INTEGRATION_AVAILABLE:
            return
        intent = " ".join((post.text or "").split())[:240].strip()
        if not intent:
            return
        try:
            service = _get_sticker_service()
            picked: dict[str, bytes] = {}

            async def deliver(source: Path) -> None:
                picked["content"] = await asyncio.to_thread(source.read_bytes)

            usage = _StickerUsageContext(
                logical_chat_key=f"qzone-feed:{uuid.uuid4().hex}",
                physical_channel_key=f"qzone-feed:{uuid.uuid4().hex}",
                agent_turn_key=f"qzone-publish:{uuid.uuid4().hex}",
            )
            result = await service.execute_send_direct(
                usage,
                reservation_owner=object(),
                intent=intent,
                reply_mode=_StickerReplyMode.IMAGE_ONLY,
                deliver=deliver,
            )
            content = picked.get("content")
            if content:
                post.images = [*(post.images or []), content]
                logger.info("Attached semantic sticker to Qzone feed")
            else:
                logger.info(f"No sticker attached to Qzone feed: {result.get('reason')}")
        except Exception as exc:
            logger.warning(f"Attach sticker failed, publishing without image: {exc}")


    async def publish_post(
        self,
        *,
        post: Post | None = None,
        text: str | None = None,
        images: list | None = None,
    ) -> Post:
        """发表帖子（支持 Post / text / images，但不能为空）"""

        # 参数校验
        if post is None and not text and not images:
            raise ValueError("post、text、images 不能同时为空")

        # 如果没传 post，就自动构造一个
        if post is None:
            uin = await self.session.get_uin()
            name = await self.session.get_nickname()
            post = Post(
                uin=uin,
                name=name,
                text=text or "",
                images=images or [],
            )

        # 尝试附加表情包配图
        await self._attach_semantic_sticker(post)

        # 发布
        resp = await self.qzone.publish(post)
        if not resp.ok:
            raise RuntimeError(f"发布说说失败：{resp.data}")

        # 回填发布结果
        post.tid = resp.data.get("tid")
        post.status = "approved"
        post.create_time = resp.data.get("now", post.create_time)

        # 持久化
        await self.db.save(post)
        return post

    async def delete_post(self, post: Post):
        """删除帖子"""
        if not post.tid:
            raise ValueError("帖子 tid 为空")
        await self.qzone.delete(post.tid)
        if post.id:
            await self.db.delete(post.id)
