from __future__ import annotations

import zoneinfo
from pathlib import Path

from ..plugin import config, plugin


class LLMConfig:
    def __init__(self) -> None:
        self.post_provider_id = ""
        self.post_prompt = config.POST_PROMPT
        self.comment_provider_id = ""
        self.comment_prompt = config.COMMENT_PROMPT


class SourceConfig:
    def __init__(self) -> None:
        self.ignore_groups = config.IGNORE_GROUPS
        self.post_max_msg = config.POST_MAX_MSG

    def is_ignore_group(self, group_id: str) -> bool:
        return str(group_id) in {str(x) for x in self.ignore_groups}


class TriggerConfig:
    def __init__(self) -> None:
        self.publish_cron = config.PUBLISH_CRON
        self.publish_offset = config.PUBLISH_OFFSET
        self.comment_cron = config.COMMENT_CRON
        self.comment_offset = config.COMMENT_OFFSET
        self.like_when_comment = config.LIKE_WHEN_COMMENT


class PluginConfig:
    _plugin_name = "nekro_plugin_qzone"

    def __init__(self) -> None:
        self.llm = LLMConfig()
        self.source = SourceConfig()
        self.trigger = TriggerConfig()

        self.data_dir = plugin.get_plugin_data_dir()
        self.temp_dir = self.data_dir / "temp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "posts_v5.db"

        self.plugin_dir = Path(__file__).resolve().parent.parent
        self.default_style_dir = self.plugin_dir / "default_style"
        self.style_dir = self.default_style_dir

        self.timezone = zoneinfo.ZoneInfo("Asia/Shanghai")
        # OneBot 机器人实例，运行时由 main 注入
        self.client = None

    @property
    def manage_group(self) -> str:
        return config.MANAGE_GROUP

    @property
    def use_builtin_renderer(self) -> bool:
        return config.USE_BUILTIN_RENDERER

    @property
    def enable_post_image(self) -> bool:
        return config.ENABLE_POST_IMAGE

    @property
    def cookie_ttl(self) -> int:
        return config.COOKIE_TTL

    @property
    def timeout(self) -> int:
        return config.TIMEOUT

    @property
    def admins_id(self) -> list[str]:
        return [str(x).strip() for x in config.ADMIN_USERS if str(x).strip().isdigit()]
