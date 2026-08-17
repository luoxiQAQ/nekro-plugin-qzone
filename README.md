# Nekro Plugin: QQ空间

适用于 NekroAgent 的 QQ 空间自然语言操作与定时发布插件。

## 功能

- 自然语言查看 QQ 空间说说
- 自然语言点赞或评论说说
- 自然语言发布说说
- 根据频道人设与群聊记录定时生成并发布说说
- 将定时发布结果通知到管理群或管理员私聊
- 可选的说说卡片渲染

## 使用方式

插件不提供斜杠指令。直接用自然语言告诉机器人需要执行的操作，例如：

- “帮我看看最新一条好友动态”
- “看看 QQ 123456 的最新说说并点赞”
- “评论一下最新动态”
- “帮我发一条说说：今天天气不错”

机器人会根据请求调用对应的 QQ 空间工具。

## 自然语言工具

| 工具 | 功能 |
| --- | --- |
| `qzone_view_feed` | 查看自己、指定 QQ 或好友动态流中的说说，并可选择点赞或评论 |
| `qzone_publish_feed` | 将指定文本发布为 QQ 空间说说 |

## 定时发布

默认每天 `22:00` 自动生成并发布一条说说，实际执行时间会在基准时间前后随机 `±600` 秒。

定时生成时会从未忽略的活跃群聊中选择一个频道，读取该频道的人设和近期聊天记录，再生成符合人设的说说内容。

将 `PUBLISH_CRON` 留空可以关闭定时发布。

## 配置说明

- `MANAGE_GROUP`：定时发布结果通知群号，留空则私聊管理员。
- `ADMIN_USERS`：用于接收定时发布结果的管理员 QQ 号列表。
- `USE_BUILTIN_RENDERER`：是否将说说渲染为卡片图片后发送。
- `MODEL_GROUP`：自然语言操作和内容生成使用的 LLM 模型组。
- `POST_PROMPT`：定时发说说的生成提示词。
- `COMMENT_PROMPT`：自然语言评论说说时使用的提示词。
- `IGNORE_GROUPS`：定时生成时不读取聊天记录的群号列表。
- `POST_MAX_MSG`：生成说说时参考的最大聊天消息数量。
- `PUBLISH_CRON`：自动发说说时间，格式 `HH:MM`，默认 `22:00`。
- `PUBLISH_OFFSET`：自动发说说时间的随机偏移秒数，默认 `600`。
- `COOKIE_TTL`：QQ 空间 Cookie 刷新间隔秒数。
- `TIMEOUT`：QQ 空间请求超时秒数。

## 部署

1. 将插件目录放入 Nekro 本地插件目录，例如：

   ```text
   /root/srv/nekro_agent/plugins/workdir/nekro_plugin_qzone
   ```

2. 安装依赖：

   ```bash
   docker exec nekro_agent /app/.venv/bin/pip install beautifulsoup4 croniter
   ```

3. 重启 Nekro 并在后台启用插件。
