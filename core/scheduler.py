from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter


_TIME_ONLY_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")

from .config import PluginConfig
from .log import logger
from .sender import Sender
from .service import PostService


class AutoRandomCronTask:
    """按 Cron 基准时间 + 随机偏移执行任务，基于 croniter + asyncio 实现"""

    def __init__(
        self,
        job_name: str,
        cron_expr: str,
        timezone: ZoneInfo,
        offset_seconds: int,
    ):
        self.job_name = job_name
        self.cron_expr = cron_expr
        self._normalized_cron_exprs: list[str] = []
        self.timezone = timezone
        self.offset_seconds = offset_seconds
        self._task: asyncio.Task | None = None
        self._terminated = False

    def _normalize_cron_exprs(self, raw: str) -> list[str]:
        entries = [part.strip() for part in re.split("[,\uff0c]", raw) if part.strip()]
        normalized: list[str] = []
        for entry in entries:
            match = _TIME_ONLY_RE.match(entry)
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2))
                if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                    raise ValueError(f"Invalid time format: {entry}")
                normalized.append(f"{minute} {hour} * * *")
            else:
                normalized.append(entry)
        seen: set[str] = set()
        unique: list[str] = []
        for expr in normalized:
            if expr not in seen:
                seen.add(expr)
                unique.append(expr)
        return unique

    def start(self) -> None:
        if not self.cron_expr or not self.cron_expr.strip():
            logger.info(f"[{self.job_name}] Cron not configured, disabled")
            return
        try:
            self._normalized_cron_exprs = self._normalize_cron_exprs(self.cron_expr)
        except ValueError as e:
            logger.error(f"[{self.job_name}] Invalid time format: {e}")
            return
        if not self._normalized_cron_exprs:
            logger.info(f"[{self.job_name}] Cron not configured, disabled")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info(f"[{self.job_name}] started, schedule: {self.cron_expr}, offset +/-{self.offset_seconds}s")
    async def _loop(self) -> None:
        while not self._terminated:
            now = datetime.now(self.timezone)
            try:
                base = min(
                    croniter(expr, now).get_next(datetime)
                    for expr in self._normalized_cron_exprs
                )
            except Exception as e:
                logger.error(f"[{self.job_name}] Cron 格式错误：{e}")
                return

            delay = (
                random.randint(-self.offset_seconds, self.offset_seconds)
                if self.offset_seconds
                else 0
            )
            target = base + timedelta(seconds=delay)
            if target <= now:
                target = now + timedelta(seconds=1)

            wait = max((target - now).total_seconds(), 0)
            try:
                await asyncio.sleep(wait)
            except asyncio.CancelledError:
                break

            if self._terminated:
                break

            try:
                await self.do_task()
            except Exception as e:
                logger.exception(f"[{self.job_name}] 任务执行失败: {e}")
            finally:
                await asyncio.sleep(1)

    async def do_task(self) -> None:
        raise NotImplementedError

    async def terminate(self) -> None:
        if self._terminated:
            return
        self._terminated = True
        if self._task:
            self._task.cancel()
        logger.info(f"[{self.job_name}] 已停止")


class AutoPublish(AutoRandomCronTask):
    def __init__(
        self,
        config: PluginConfig,
        service: PostService,
        sender: Sender,
    ):
        super().__init__(
            "AutoPublish",
            config.trigger.publish_cron,
            config.timezone,
            config.trigger.publish_offset,
        )
        self.cfg = config
        self.service = service
        self.sender = sender

    async def _pick_group_chat_key(self) -> str | None:
        """从活跃的群聊频道中随机选一个（排除忽略的群）"""
        from nekro_agent.models.db_chat_channel import DBChatChannel

        channels = await DBChatChannel.filter(
            is_active=True,
            channel_type="group",
        ).all()
        candidates = []
        for ch in channels:
            group_id = ch.channel_id
            if self.cfg.source.is_ignore_group(group_id):
                continue
            candidates.append(ch)
        if not candidates:
            return None
        chosen = random.choice(candidates)
        return chosen.chat_key

    async def _get_persona(self, chat_key: str) -> str:
        """获取指定频道的人设内容"""
        from nekro_agent.models.db_chat_channel import DBChatChannel

        try:
            channel = await DBChatChannel.get_channel(chat_key)
            preset = await channel.get_preset()
            return preset.content if hasattr(preset, "content") and preset.content else ""
        except Exception as e:
            logger.warning(f"获取人设失败（{chat_key}）：{e}")
            return ""

    _RETRY_DELAYS = (10, 30, 60)

    async def do_task(self) -> None:
        chat_key = await self._pick_group_chat_key()
        if not chat_key:
            logger.warning(f"[{self.job_name}] 无可用群聊频道，跳过定时发说说")
            chat_key = ""

        persona = ""
        if chat_key:
            persona = await self._get_persona(chat_key)
            if persona:
                logger.info(f"[{self.job_name}] 使用频道 {chat_key} 的人设生成说说")
            else:
                logger.info(f"[{self.job_name}] 频道 {chat_key} 无人设，使用默认提示词")

        text: str | None = None
        last_error: Exception | None = None
        max_attempts = len(self._RETRY_DELAYS) + 1

        for attempt in range(max_attempts):
            try:
                text = await self.service.llm.generate_post(
                    chat_key=chat_key,
                    persona=persona,
                )
                break
            except Exception as e:
                last_error = e
                if attempt < len(self._RETRY_DELAYS):
                    delay = self._RETRY_DELAYS[attempt]
                    logger.warning(
                        f"[{self.job_name}] LLM 调用失败（第 {attempt + 1} 次），"
                        f"{delay}秒后重试… 错误：{e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"[{self.job_name}] LLM 调用连续失败 {max_attempts} 次，放弃。最后错误：{e}"
                    )

        if text is None:
            err_msg = (
                f"⚠️ 定时发说说失败\n"
                f"LLM 调用连续 {max_attempts} 次均超时/失败\n"
                f"最后错误：{last_error}"
            )
            await self.sender.send_admin_msg(err_msg)
            return

        post = await self.service.publish_post(text=text)
        await self.sender.send_admin_post(post, message="定时发说说")

class AutoComment(AutoRandomCronTask):
    """定时评论好友动态"""
    def __init__(
        self,
        config: PluginConfig,
        service: PostService,
        sender: Sender,
    ):
        super().__init__(
            "AutoComment",
            config.trigger.comment_cron,
            config.timezone,
            config.trigger.comment_offset,
        )
        self.cfg = config
        self.service = service
        self.sender = sender

    async def do_task(self) -> None:
        try:
            posts = await self.service.query_feeds(
                pos=0,
                num=20,
                no_self=True,
                no_commented=True,
            )
        except Exception as e:
            logger.warning(f"[{self.job_name}] 获取动态流失败: {e}")
            return

        if not posts:
            logger.info(f"[{self.job_name}] 暂无未评论的说说")
            return

        for post in posts:
            try:
                await self.service.comment_posts(post)
                if self.cfg.trigger.like_when_comment:
                    await self.service.like_posts(post)
                await self.sender.send_admin_post(post, message="定时评论")
            except Exception as e:
                logger.exception(
                    f"[{self.job_name}] 评论失败 tid={post.tid}, uin={post.uin}, name={post.name}: {e}"
                )

