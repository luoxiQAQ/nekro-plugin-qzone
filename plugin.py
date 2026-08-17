from __future__ import annotations

from pydantic import Field

from nekro_agent.api.plugin import ConfigBase, ExtraField, NekroPlugin

plugin = NekroPlugin(
    name="QQ空间",
    module_name="nekro_plugin_qzone",
    description="QQ空间自然语言操作与定时发说说插件",
    version="1.1.2",
    author="LuoXi",
    url="https://github.com/luoxiQAQ/nekro-plugin-qzone",
    allow_sleep=False,
)


@plugin.mount_config()
class QzoneConfig(ConfigBase):
    MANAGE_GROUP: str = Field(default="", title="管理群号", description="定时发说说的通知发送到该群，留空则私聊管理员")
    ADMIN_USERS: list[str] = Field(default=[], title="管理员QQ号", description="用于接收定时发布结果的管理员QQ号列表")
    USE_BUILTIN_RENDERER: bool = Field(default=True, title="启用卡片渲染", description="将说说渲染为卡片图片后发送")
    MODEL_GROUP: str = Field(
        default="",
        title="LLM模型组",
        description="写说说/评论使用的模型组，留空则使用频道默认模型组（定时任务建议显式配置）",
        json_schema_extra=ExtraField(ref_model_groups=True, model_type="chat").model_dump(),
    )
    POST_PROMPT: str = Field(
        default="根据你的人设和今天在各个群聊的经历写一个说说",
        title="写说说提示词",
        json_schema_extra=ExtraField(is_textarea=True).model_dump(),
    )
    COMMENT_PROMPT: str = Field(
        default="根据你的人设写一个评论",
        title="评论提示词",
        json_schema_extra=ExtraField(is_textarea=True).model_dump(),
    )
    IGNORE_GROUPS: list[str] = Field(default=[], title="忽略的群聊", description="不会从这些群抽取聊天记录写说说")
    POST_MAX_MSG: int = Field(default=500, title="写说说参考消息数", description="从群聊抽取用于写说说的最大消息条数", ge=100, le=1000)
    PUBLISH_CRON: str = Field(default="22:00", title="自动发说说时间", description="格式：HH:MM（例如 22:00）。留空禁用")
    PUBLISH_OFFSET: int = Field(default=600, title="自动发说说偏移秒数", description="在Cron基准时间前后随机浮动", ge=0, le=3600)
    COOKIE_TTL: int = Field(default=600, title="Cookie刷新间隔秒数", ge=0, le=86400)
    TIMEOUT: int = Field(default=10, title="请求超时秒数", ge=5, le=60)


config: QzoneConfig = plugin.get_config(QzoneConfig)
