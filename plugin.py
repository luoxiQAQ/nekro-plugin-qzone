from __future__ import annotations

from pydantic import Field

from nekro_agent.api.plugin import ConfigBase, ExtraField, NekroPlugin

plugin = NekroPlugin(
    name="QQ空间",
    module_name="nekro_plugin_qzone",
    description="QQ空间对接插件：查看/点赞/评论说说、自然语言发说说、表白墙投稿审核、定时发说说与评论",
    version="1.0.0",
    author="luoxiQAQ",
    url="https://github.com/luoxiQAQ/nekro-plugin-qzone",
    allow_sleep=False,
)


@plugin.mount_config()
class QzoneConfig(ConfigBase):
    MANAGE_GROUP: str = Field(default="", title="管理群号", description="投稿审核/定时任务通知发送到该群，留空则私聊管理员")
    ADMIN_USERS: list[str] = Field(default=[], title="管理员QQ号", description="用于接收审核通知和定时任务反馈的管理员QQ号列表")
    USE_BUILTIN_RENDERER: bool = Field(default=True, title="启用卡片渲染", description="将说说渲染为卡片图片后发送")
    MODEL_GROUP: str = Field(
        default="",
        title="LLM模型组",
        description="写说说/评论/回复使用的模型组，留空则使用频道默认模型组（定时任务建议显式配置）",
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
    REPLY_PROMPT: str = Field(
        default="这条帖子收到了一条评论，根据你的人设写一个回复",
        title="回复提示词",
        json_schema_extra=ExtraField(is_textarea=True).model_dump(),
    )
    IGNORE_GROUPS: list[str] = Field(default=[], title="忽略的群聊", description="不会从这些群抽取聊天记录写说说")
    IGNORE_USERS: list[str] = Field(default=[], title="忽略的用户", description="空间未开放的用户会被自动加入此列表")
    POST_MAX_MSG: int = Field(default=500, title="写说说参考消息数", description="从群聊抽取用于写说说的最大消息条数", ge=100, le=1000)
    PUBLISH_CRON: str = Field(default="22:00", title="自动发说说时间", description="格式：HH:MM（例如 22:00）。留空禁用")
    PUBLISH_OFFSET: int = Field(default=600, title="自动发说说偏移秒数", description="在Cron基准时间前后随机浮动", ge=0, le=3600)
    COMMENT_CRON: str = Field(default="08:00", title="自动评论时间", description="格式：HH:MM（例如 08:00）。留空禁用")
    COMMENT_OFFSET: int = Field(default=600, title="自动评论偏移秒数", description="在Cron基准时间前后随机浮动", ge=0, le=3600)
    READ_PROB: float = Field(default=0.0, title="聊天触发评说说概率", ge=0.0, le=1.0)
    SEND_ADMIN: bool = Field(default=True, title="触发读说说时仅通知管理员")
    LIKE_WHEN_COMMENT: bool = Field(default=True, title="评说说时自动点赞")
    COOKIE_TTL: int = Field(default=600, title="Cookie刷新间隔秒数", ge=0, le=86400)
    TIMEOUT: int = Field(default=10, title="请求超时秒数", ge=5, le=60)
    SHOW_NAME: bool = Field(default=True, title="显示投稿人昵称")


config: QzoneConfig = plugin.get_config(QzoneConfig)
