from __future__ import annotations

import random
from typing import Annotated

from nekro_agent.api.plugin import (
    Arg,
    CommandExecutionContext,
    CommandPermission,
    CommandResponse,
    CmdCtl,
    SandboxMethodType,
)
from nekro_agent.schemas.agent_ctx import AgentCtx
from nekro_agent.models.db_chat_channel import DBChatChannel
from nekro_agent.schemas.chat_message import ChatMessage
from nekro_agent.schemas.signal import MsgSignal

from .core.campus_wall import CampusWall
from .core.config import PluginConfig
from .core.db import PostDB
from .core.llm_action import LLMAction
from .core.log import logger
from .core.model import Post
from .core.qzone import QzoneAPI, QzoneSession
from .core.scheduler import AutoComment, AutoPublish
from .core.sender import Sender
from .core.service import PostService
from .core.utils import extract_image_urls
from .plugin import config, plugin

cfg = PluginConfig()
session: QzoneSession | None = None
qzone: QzoneAPI | None = None
db: PostDB | None = None
llm: LLMAction | None = None
sender: Sender | None = None
service: PostService | None = None
campus_wall: CampusWall | None = None

auto_comment: AutoComment | None = None
auto_publish: AutoPublish | None = None


def _success(message: str) -> CommandResponse:
    return CmdCtl.success(message)


def _failed(exc: Exception) -> CommandResponse:
    logger.exception(str(exc))
    return CmdCtl.failed(str(exc))


def _group_id_from_chat_key(chat_key: str) -> int:
    if "_group_" in chat_key:
        try:
            return int(chat_key.rsplit("_", 1)[-1])
        except ValueError:
            return 0
    return 0


async def _get_single_post(
    *,
    target_id: str,
    pos: int,
    with_detail: bool = True,
) -> Post:
    """按目标 QQ 号和序号取一条说说；目标为空时取好友动态流"""
    if not target_id.strip():
        target_id = None
    posts = await service.query_feeds(
        target_id=target_id,
        pos=max(pos - 1, 0),
        num=1,
        with_detail=with_detail,
    )
    if not posts:
        raise RuntimeError("没有查询到说说")
    return posts[0]


@plugin.mount_init_method()
async def init_plugin() -> None:
    global session, qzone, db, llm, sender, service, campus_wall, auto_comment, auto_publish

    session = QzoneSession(cfg)
    qzone = QzoneAPI(session, cfg)
    db = PostDB(cfg)
    llm = LLMAction(cfg)
    sender = Sender(cfg)
    service = PostService(qzone, session, db, llm)
    campus_wall = CampusWall(cfg, service, db, sender)

    await db.initialize()

    if not auto_comment and cfg.trigger.comment_cron.strip():
        auto_comment = AutoComment(cfg, service, sender)
        auto_comment.start()

    if not auto_publish and cfg.trigger.publish_cron.strip():
        auto_publish = AutoPublish(cfg, service, sender)
        auto_publish.start()

    logger.info("QQ空间插件初始化完成")


@plugin.mount_cleanup_method()
async def cleanup_plugin() -> None:
    if auto_comment:
        await auto_comment.terminate()
    if auto_publish:
        await auto_publish.terminate()
    if qzone:
        await qzone.close()
    logger.info("QQ空间插件资源已释放")


# ============================================================
# 用户命令
# ============================================================

@plugin.mount_command(
    name="qzone_visitor",
    description="查看QQ空间访客",
    aliases=['查看访客', '访客', 'na-查看访客', 'na-访客'],
    permission=CommandPermission.PUBLIC,
)
async def view_visitor(context: CommandExecutionContext) -> CommandResponse:
    try:
        return _success(await service.view_visitor())
    except Exception as exc:
        return _failed(exc)


@plugin.mount_command(
    name="qzone_feed",
    description="查看自己或指定QQ号的说说",
    aliases=['看说说', '查说说', 'na-看说说', 'na-查说说'],
    permission=CommandPermission.PUBLIC,
)
async def view_feed(
    context: CommandExecutionContext,
    target_id: Annotated[str, Arg("目标QQ号，留空查看好友动态", positional=True)] = "",
    pos: Annotated[int, Arg("说说序号，从1开始", positional=True)] = 1,
) -> CommandResponse:
    try:
        post = await _get_single_post(target_id=target_id, pos=pos)
        await sender.send_post(context.chat_key, post)
        return _success("已发送说说")
    except Exception as exc:
        return _failed(exc)


@plugin.mount_command(
    name="qzone_like",
    description="点赞自己或指定QQ号的说说",
    aliases=['赞说说', '点赞说说', 'na-赞说说', 'na-点赞说说'],
    permission=CommandPermission.PUBLIC,
)
async def like_feed(
    context: CommandExecutionContext,
    target_id: Annotated[str, Arg("目标QQ号，留空查看好友动态", positional=True)] = "",
    pos: Annotated[int, Arg("说说序号，从1开始", positional=True)] = 1,
) -> CommandResponse:
    try:
        post = await _get_single_post(target_id=target_id, pos=pos)
        await service.like_posts(post)
        await sender.send_post(context.chat_key, post, message="已点赞")
        return _success("已点赞")
    except Exception as exc:
        return _failed(exc)


@plugin.mount_command(
    name="qzone_comment",
    description="用AI评论自己或指定QQ号的说说",
    aliases=['评说说', '评论说说', 'na-评说说', 'na-评论说说'],
    permission=CommandPermission.PUBLIC,
)
async def comment_feed(
    context: CommandExecutionContext,
    target_id: Annotated[str, Arg("目标QQ号，留空查看好友动态", positional=True)] = "",
    pos: Annotated[int, Arg("说说序号，从1开始", positional=True)] = 1,
) -> CommandResponse:
    try:
        post = await _get_single_post(target_id=target_id, pos=pos)
        await service.comment_posts(post, chat_key=context.chat_key)
        await sender.send_post(context.chat_key, post, message="已评论")
        return _success("已评论")
    except Exception as exc:
        return _failed(exc)


@plugin.mount_command(
    name="qzone_reply",
    description="用AI回复说说的指定评论",
    aliases=['回评', '回复评论', 'na-回评', 'na-回复评论'],
    permission=CommandPermission.PUBLIC,
)
async def reply_feed(
    context: CommandExecutionContext,
    target_id: Annotated[str, Arg("目标QQ号", positional=True)] = "",
    pos: Annotated[int, Arg("说说序号，从1开始", positional=True)] = 1,
    index: Annotated[int, Arg("评论序号，从1开始", positional=True)] = 1,
) -> CommandResponse:
    try:
        post = await _get_single_post(target_id=target_id, pos=pos)
        await service.reply_comment(post, index=max(index - 1, 0), chat_key=context.chat_key)
        await sender.send_post(context.chat_key, post, message="已回复评论")
        return _success("已回复评论")
    except Exception as exc:
        return _failed(exc)


@plugin.mount_command(
    name="qzone_delete",
    description="删除自己的说说",
    aliases=['删说说', '删除说说', 'na-删说说', 'na-删除说说'],
    permission=CommandPermission.PUBLIC,
)
async def delete_feed(
    context: CommandExecutionContext,
    tid: Annotated[str, Arg("说说ID", positional=True)],
) -> CommandResponse:
    try:
        await service.delete_post(Post(tid=tid))
        return _success("已删除说说")
    except Exception as exc:
        return _failed(exc)


# ============================================================
# 表白墙 / 投稿
# ============================================================

@plugin.mount_command(
    name="qzone_contribute",
    description="向QQ空间表白墙投稿",
    aliases=['投稿', '表白墙投稿', 'na-投稿', 'na-表白墙投稿'],
    permission=CommandPermission.PUBLIC,
)
async def contribute(
    context: CommandExecutionContext,
    content: Annotated[str, Arg("投稿内容，可附带图片链接", positional=True, greedy=True)] = "",
) -> CommandResponse:
    try:
        if not content.strip():
            return CmdCtl.failed("投稿内容不能为空")
        result = await campus_wall.contribute(
            chat_key=context.chat_key,
            user_id=context.user_id,
            username=context.username,
            gin=_group_id_from_chat_key(context.chat_key),
            text=content,
            images=extract_image_urls(content),
            anon=False,
        )
        return _success(result)
    except Exception as exc:
        return _failed(exc)


@plugin.mount_command(
    name="qzone_contribute_anon",
    description="匿名向QQ空间表白墙投稿",
    aliases=['匿名投稿', 'na-匿名投稿'],
    permission=CommandPermission.PUBLIC,
)
async def contribute_anon(
    context: CommandExecutionContext,
    content: Annotated[str, Arg("匿名投稿内容，可附带图片链接", positional=True, greedy=True)] = "",
) -> CommandResponse:
    try:
        if not content.strip():
            return CmdCtl.failed("投稿内容不能为空")
        result = await campus_wall.contribute(
            chat_key=context.chat_key,
            user_id=context.user_id,
            username=context.username,
            gin=_group_id_from_chat_key(context.chat_key),
            text=content,
            images=extract_image_urls(content),
            anon=True,
        )
        return _success(result)
    except Exception as exc:
        return _failed(exc)


@plugin.mount_command(
    name="qzone_recall",
    description="撤回自己投出的稿件",
    aliases=['撤稿', 'na-撤稿'],
    permission=CommandPermission.PUBLIC,
)
async def recall_post(
    context: CommandExecutionContext,
    post_id: Annotated[int, Arg("稿件ID", positional=True)],
    reason: Annotated[str, Arg("撤稿原因", positional=True, greedy=True)] = "",
) -> CommandResponse:
    try:
        result = await campus_wall.delete(
            user_id=context.user_id,
            post_id=post_id,
            reason=reason,
        )
        return _success(result)
    except Exception as exc:
        return _failed(exc)


@plugin.mount_command(
    name="qzone_view_post",
    description="查看稿件",
    aliases=['看稿', '查看稿件', 'na-看稿', 'na-查看稿件'],
    permission=CommandPermission.SUPER_USER,
)
async def view_post(
    context: CommandExecutionContext,
    post_id: Annotated[int, Arg("稿件ID", positional=True)],
) -> CommandResponse:
    try:
        result = await campus_wall.view(chat_key=context.chat_key, post_id=post_id)
        return _success(result)
    except Exception as exc:
        return _failed(exc)


@plugin.mount_command(
    name="qzone_approve_post",
    description="通过稿件并发布到QQ空间",
    aliases=['过稿', '通过稿件', 'na-过稿', 'na-通过稿件'],
    permission=CommandPermission.SUPER_USER,
)
async def approve_post(
    context: CommandExecutionContext,
    post_id: Annotated[int, Arg("稿件ID", positional=True)],
) -> CommandResponse:
    try:
        result = await campus_wall.approve(chat_key=context.chat_key, post_id=post_id)
        return _success(result)
    except Exception as exc:
        return _failed(exc)


@plugin.mount_command(
    name="qzone_reject_post",
    description="拒绝稿件",
    aliases=['拒稿', '拒绝稿件', 'na-拒稿', 'na-拒绝稿件'],
    permission=CommandPermission.SUPER_USER,
)
async def reject_post(
    context: CommandExecutionContext,
    post_id: Annotated[int, Arg("稿件ID", positional=True)],
    reason: Annotated[str, Arg("拒绝原因", positional=True, greedy=True)] = "",
) -> CommandResponse:
    try:
        result = await campus_wall.reject(
            chat_key=context.chat_key,
            post_id=post_id,
            reason=reason,
        )
        return _success(result)
    except Exception as exc:
        return _failed(exc)


# ============================================================

# ============================================================
# AI 生成说说
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
        pos (int): 要查看的说说不序号，0 表示最新一条。
        like (bool): 是否点赞这条说说。
        reply (bool): 是否评论这条说说。

    Returns:
        str: 操作结果和说说内容摘要。

    Example:
        llm_view_feed("123456", pos=0, like=False, reply=True)
    """
    try:
        target_id = user_id or ""
        post = await _get_single_post(target_id=target_id, pos=pos + 1)
        message = ""

        if like and reply:
            await service.comment_posts(post, chat_key=_ctx.chat_key)
            await service.like_posts(post)
            message = "已评论并点赞"
        elif reply:
            await service.comment_posts(post, chat_key=_ctx.chat_key)
            message = "已评论"
        elif like:
            await service.like_posts(post)
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
) -> str:
    """写一篇说说并发布到 QQ 空间。

    Args:
        text (str): 要发布的说说内容。

    Returns:
        str: 发布结果。

    Example:
        llm_publish_feed("今天天气真不错")
    """
    try:
        if not text.strip():
            return "说说内容不能为空"
        post = await service.publish_post(text=text)
        return "\u5df2\u7ecf\u53d1\u5e03\u8bf4\u8bf4\u5230QQ\u7a7a\u95f4\uff0c\u5185\u5bb9\u662f\uff1a\n" + post.text
    except Exception as exc:
        logger.exception(str(exc))
        return str(exc)


# ============================================================
# 聊天触发
# ============================================================

@plugin.mount_on_user_message()
async def on_user_message(_ctx: AgentCtx, message: ChatMessage) -> MsgSignal | None:
    try:
        if not message.content_text.strip() or message.sender_id == "-1":
            return MsgSignal.CONTINUE

        if cfg.source.is_ignore_group(_group_id_from_chat_key(_ctx.chat_key)):
            return MsgSignal.CONTINUE
        if cfg.source.is_ignore_user(message.sender_id):
            return MsgSignal.CONTINUE

        if random.random() >= cfg.trigger.read_prob:
            return MsgSignal.CONTINUE

        posts = await service.query_feeds(
            pos=0,
            num=1,
            no_self=True,
            no_commented=True,
        )
        if not posts:
            return MsgSignal.CONTINUE

        post = posts[0]
        await service.comment_posts(post, chat_key=_ctx.chat_key)
        if cfg.trigger.like_when_comment:
            await service.like_posts(post)

        if cfg.trigger.send_admin:
            await sender.send_admin_post(post, message="聊天触发说说")
        else:
            await sender.send_post(_ctx.chat_key, post, message="聊天触发说说")
        return MsgSignal.CONTINUE
    except Exception as exc:
        logger.exception(f"聊天触发说说失败: {exc}")
        return MsgSignal.CONTINUE