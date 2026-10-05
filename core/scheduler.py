from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter


_TIME_ONLY_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")

from .accounts import AccountSpec, get_account_persona, get_chat_persona, list_accounts
from .config import PluginConfig
from .log import logger
from .sender import Sender
from .service import PostService


async def _ensure_account_login(service: PostService, spec: AccountSpec, job_name: str) -> bool:
    """预检账号 QQ 空间登录态；失败则跳过该账号（例如无 web 态的官方 bot）。"""
    try:
        session, _qzone = service.accounts.resolve(spec.id)
        ctx = await asyncio.wait_for(session.get_ctx(), timeout=30)
    except Exception as e:
        logger.warning(f"[{job_name}] 账号 {spec.display} 登录 QQ 空间不可用，跳过：{e}")
        return False
    logger.info(f"[{job_name}] 账号 {spec.display} 登录态正常（uin={ctx.uin}）")
    return True


class AutoRandomScheduleTask:
    """定时任务调度：cron 基准时间 + 随机偏移，或每 N 天内随机时刻（由 interval_days 决定）"""

    def __init__(
        self,
        job_name: str,
        cron_expr: str,
        timezone: ZoneInfo,
        offset_seconds: int,
        interval_days: float = 0,
    ):
        self.job_name = job_name
        self.cron_expr = cron_expr
        self._normalized_cron_exprs: list[str] = []
        self.timezone = timezone
        self.offset_seconds = offset_seconds
        self.interval_days = interval_days
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
        if self.interval_days > 0:
            self._task = asyncio.create_task(self._interval_loop())
            logger.info(
                f"[{self.job_name}] started, 每 {self.interval_days:g} 天内随机时刻"
            )
            return
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

    async def _interval_loop(self) -> None:
        """每 interval_days 天为一个周期，在周期内随机时刻执行一次（长期平均间隔 = interval_days 天）"""
        interval = timedelta(days=self.interval_days)
        window_start = datetime.now(self.timezone)
        while not self._terminated:
            now = datetime.now(self.timezone)
            if window_start <= now - interval:
                window_start = now
            fire_at = window_start + timedelta(
                seconds=random.uniform(0, interval.total_seconds())
            )
            logger.info(f"[{self.job_name}] 下次执行时间: {fire_at:%Y-%m-%d %H:%M:%S}")
            wait = max((fire_at - now).total_seconds(), 0)
            try:
                await asyncio.sleep(wait)
            except asyncio.CancelledError:
                break

            if self._terminated:
                break

            window_start += interval
            try:
                await self.do_task()
            except Exception as e:
                logger.exception(f"[{self.job_name}] 任务执行失败: {e}")
            finally:
                await asyncio.sleep(1)

    async def _loop(self) -> None:
        last_base: datetime | None = None
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

            if last_base is not None and base <= last_base:
                base = min(
                    croniter(expr, last_base + timedelta(seconds=1)).get_next(datetime)
                    for expr in self._normalized_cron_exprs
                )

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

            last_base = base
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


class AutoPublish(AutoRandomScheduleTask):
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
            config.trigger.publish_interval_days,
        )
        self.cfg = config
        self.service = service
        self.sender = sender

    async def _pick_group_chat_key(self, account_id: str) -> str | None:
        """从该账号的活跃群聊频道中随机选一个（排除忽略的群）"""
        from nekro_agent.adapters.onebot_v11.core.channel_scope import split_scoped_channel_id
        from nekro_agent.models.db_chat_channel import DBChatChannel

        channels = await DBChatChannel.filter(
            is_active=True,
            channel_type="group",
        ).all()
        candidates = []
        for ch in channels:
            scope_id, raw_channel_id = split_scoped_channel_id(ch.channel_id)
            if account_id:
                if scope_id != account_id:
                    continue
            elif scope_id:
                continue
            group_id = raw_channel_id.removeprefix("group_")
            if self.cfg.source.is_ignore_group(group_id):
                continue
            candidates.append(ch)
        if not candidates:
            return None
        chosen = random.choice(candidates)
        return chosen.chat_key

    _RETRY_DELAYS = (10, 30, 60)

    async def do_task(self) -> None:
        accounts = list_accounts()
        logger.info(
            f"[{self.job_name}] 本轮账号：" + "、".join(spec.display for spec in accounts)
        )
        for index, spec in enumerate(accounts):
            if index:
                await asyncio.sleep(random.uniform(3, 10))
            try:
                await self._publish_for_account(spec)
            except Exception as e:
                logger.exception(f"[{self.job_name}] 账号 {spec.display} 发说说失败: {e}")

    async def _publish_for_account(self, spec: AccountSpec) -> None:
        if not await _ensure_account_login(self.service, spec, self.job_name):
            return

        chat_key = await self._pick_group_chat_key(spec.id) or ""
        persona = await get_chat_persona(chat_key) if chat_key else ""
        source = f"频道 {chat_key} 的人设" if persona else ""
        if not persona:
            persona = await get_account_persona(spec.id)
            source = "账号默认人设" if persona else ""
        if persona:
            logger.info(f"[{self.job_name}] 账号 {spec.display} 使用{source}生成说说")
        else:
            logger.info(f"[{self.job_name}] 账号 {spec.display} 未拿到人设，使用默认提示词")
        if not chat_key:
            logger.warning(f"[{self.job_name}] 账号 {spec.display} 无可用群聊频道，不参考聊天记录")

        text: str | None = None
        use_sticker: bool = False
        last_error: Exception | None = None
        max_attempts = len(self._RETRY_DELAYS) + 1

        for attempt in range(max_attempts):
            try:
                text, use_sticker = await self.service.llm.generate_post(
                    chat_key=chat_key,
                    persona=persona,
                )
                break
            except Exception as e:
                last_error = e
                if attempt < len(self._RETRY_DELAYS):
                    delay = self._RETRY_DELAYS[attempt]
                    logger.warning(
                        f"[{self.job_name}] 账号 {spec.display} LLM 调用失败（第 {attempt + 1} 次），"
                        f"{delay}秒后重试… 错误：{e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"[{self.job_name}] 账号 {spec.display} LLM 调用连续失败 {max_attempts} 次，放弃。最后错误：{e}"
                    )

        if text is None:
            err_msg = (
                f"⚠️ 定时发说说失败（{spec.display}）\n"
                f"LLM 调用连续 {max_attempts} 次均超时/失败\n"
                f"最后错误：{last_error}"
            )
            await self.sender.send_admin_msg(err_msg, account_id=spec.id)
            return

        post = await self.service.publish_post(
            text=text, with_sticker=use_sticker, account_id=spec.id
        )
        await self.sender.send_admin_post(
            post, message=f"定时发说说（{spec.display}）", account_id=spec.id
        )


class AutoComment(AutoRandomScheduleTask):
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
            config.trigger.comment_interval_days,
        )
        self.cfg = config
        self.service = service
        self.sender = sender

    async def do_task(self) -> None:
        accounts = list_accounts()
        logger.info(
            f"[{self.job_name}] 本轮账号：" + "、".join(spec.display for spec in accounts)
        )
        for index, spec in enumerate(accounts):
            if index:
                await asyncio.sleep(random.uniform(3, 10))
            try:
                await self._comment_for_account(spec)
            except Exception as e:
                logger.exception(f"[{self.job_name}] 账号 {spec.display} 评论失败: {e}")

    async def _comment_for_account(self, spec: AccountSpec) -> None:
        if not await _ensure_account_login(self.service, spec, self.job_name):
            return

        persona = await get_account_persona(spec.id)
        try:
            posts = await self.service.query_feeds(
                pos=0,
                num=20,
                no_self=True,
                no_commented=True,
                account_id=spec.id,
            )
        except Exception as e:
            logger.warning(f"[{self.job_name}] 账号 {spec.display} 获取动态流失败: {e}")
            return

        if not posts:
            logger.info(f"[{self.job_name}] 账号 {spec.display} 暂无未评论的说说")
            return

        for post in posts:
            try:
                await self.service.comment_posts(post, account_id=spec.id, persona=persona)
                if self.cfg.trigger.like_when_comment:
                    await self.service.like_posts(post, account_id=spec.id)
                await self.sender.send_admin_post(
                    post, message=f"定时评论（{spec.display}）", account_id=spec.id
                )
            except Exception as e:
                logger.exception(
                    f"[{self.job_name}] 账号 {spec.display} 评论失败 tid={post.tid}, uin={post.uin}, name={post.name}: {e}"
                )
