from __future__ import annotations

from nekro_agent.api.plugin import SandboxMethodType
from nekro_agent.schemas.agent_ctx import AgentCtx

from .core.accounts import AccountRegistry, get_chat_persona, list_accounts, resolve_account_id
from .core.config import PluginConfig
from .core.db import PostDB
from .core.llm_action import LLMAction
from .core.log import logger
from .core.model import Post
from .core.scheduler import AutoComment, AutoPublish
from .core.sender import Sender
from .core.service import PostService
from .plugin import plugin

cfg = PluginConfig()
db: PostDB | None = None
llm: LLMAction | None = None
sender: Sender | None = None
service: PostService | None = None

auto_publish: AutoPublish | None = None
auto_comment: AutoComment | None = None


async def _get_single_post(
    *,
    target_id: str,
    pos: int,
    with_detail: bool = True,
    account_id: str = "",
) -> Post:
    """按目标 QQ 号和序号取一条说说；目标为空时取好友动态流"""
    if not target_id.strip():
        target_id = None
    posts = await service.query_feeds(
        target_id=target_id,
        pos=max(pos - 1, 0),
        num=1,
        with_detail=with_detail,
        account_id=account_id,
    )
    if not posts:
        raise RuntimeError("没有查询到说说")
    return posts[0]


@plugin.mount_init_method()
async def init_plugin() -> None:
    global db, llm, sender, service, auto_publish, auto_comment

    registry = AccountRegistry(cfg)
    db = PostDB(cfg)
    llm = LLMAction(cfg)
    sender = Sender(cfg)
    service = PostService(registry, db, llm, cfg)

    await db.initialize()

    if not auto_publish and (
        cfg.trigger.publish_cron.strip() or cfg.trigger.publish_interval_days > 0
    ):
        auto_publish = AutoPublish(cfg, service, sender)
        auto_publish.start()

    if not auto_comment and (
        cfg.trigger.comment_cron.strip() or cfg.trigger.comment_interval_days > 0
    ):
        auto_comment = AutoComment(cfg, service, sender)
        auto_comment.start()

    accounts = list_accounts()
    if accounts and (accounts[0].id or accounts[0].qq):
        logger.info("QQ空间插件初始化完成，账号实例：" + "、".join(a.display for a in accounts))
    else:
        logger.info("QQ空间插件初始化完成（未检测到多账号配置，按单账号模式运行）")


@plugin.mount_cleanup_method()
async def cleanup_plugin() -> None:
    if auto_publish:
        await auto_publish.terminate()
    if auto_comment:
        await auto_comment.terminate()
    if service:
        await service.accounts.close()
    logger.info("QQ空间插件资源已释放")


# ============================================================
# 自然语言工具
# ============================================================

@plugin.mount_sandbox_method(
    SandboxMethodType.TOOL,
    name="qzone_view_feed",
    description="查看QQ空间说说，也可以点赞或评论",
)
async def llm_view_feed(
    _ctx: AgentCtx,
    user_id: str = "",
    pos: int = 0,
    like: bool = False,
    reply: bool = False,
) -> str:
    """查看 QQ 空间说说，也可以点赞或评论。

    Args:
        user_id (str): 目标 QQ 号，留空表示查看好友动态流。
        pos (int): 要查看的说说序号，0 表示最新一条。
        like (bool): 是否点赞这条说说。
        reply (bool): 是否评论这条说说。

    Returns:
        str: 操作结果和说说内容摘要。

    Example:
        llm_view_feed("123456", pos=0, like=False, reply=True)
    """
    try:
        target_id = user_id or ""
        account_id = resolve_account_id(_ctx.chat_key)
        post = await _get_single_post(target_id=target_id, pos=pos + 1, account_id=account_id)
        message = ""

        if like and reply:
            persona = await get_chat_persona(_ctx.chat_key)
            await service.comment_posts(
                post, chat_key=_ctx.chat_key, account_id=account_id, persona=persona
            )
            await service.like_posts(post, account_id=account_id)
            message = "已评论并点赞"
        elif reply:
            persona = await get_chat_persona(_ctx.chat_key)
            await service.comment_posts(
                post, chat_key=_ctx.chat_key, account_id=account_id, persona=persona
            )
            message = "已评论"
        elif like:
            await service.like_posts(post, account_id=account_id)
            message = "已点赞"

        await sender.send_post(_ctx.chat_key, post, message=message)
        return "\n".join(
            part
            for part in (message, post.text, *post.images)
            if part
        )
    except Exception as exc:
        logger.exception(str(exc))
        return str(exc)


@plugin.mount_sandbox_method(
    SandboxMethodType.TOOL,
    name="qzone_publish_feed",
    description="写一篇说说并发布到QQ空间",
)
async def llm_publish_feed(
    _ctx: AgentCtx,
    text: str = "",
    with_sticker: bool = False,
) -> str:
    """写一篇说说并发布到 QQ 空间。

    Args:
        text (str): 要发布的说说内容。
        with_sticker (bool): 是否配一张表情包图片，由你判断内容是否适合。

    Returns:
        str: 发布结果。

    Example:
        llm_publish_feed("今天天气真不错", with_sticker=False)
    """
    try:
        if not text.strip():
            return "说说内容不能为空"
        account_id = resolve_account_id(_ctx.chat_key)
        post = await service.publish_post(
            text=text, with_sticker=with_sticker, account_id=account_id
        )
        return "\u5df2\u7ecf\u53d1\u5e03\u8bf4\u8bf4\u5230QQ\u7a7a\u95f4\uff0c\u5185\u5bb9\u662f\uff1a\n" + post.text
    except Exception as exc:
        logger.exception(str(exc))
        return str(exc)
