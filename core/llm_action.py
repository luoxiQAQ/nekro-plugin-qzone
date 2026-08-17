from __future__ import annotations

import re
from typing import Any

from nekro_agent.core.config import config as core_config
from nekro_agent.models.db_chat_channel import DBChatChannel
from nekro_agent.models.db_chat_message import DBChatMessage
from nekro_agent.services.agent.openai import gen_openai_chat_response

from ..plugin import config
from .config import PluginConfig
from .log import logger
from .model import Post


class LLMAction:
    def __init__(self, config: PluginConfig):
        self.cfg = config

    @staticmethod
    def _join_prompt_parts(*parts: str) -> str:
        return "\n\n".join(part.strip() for part in parts if part and part.strip())

    @staticmethod
    def extract_content(raw: str) -> str:
        marker = '"""'
        start = raw.find(marker) + len(marker)
        end = raw.find(marker, start)
        if start > len(marker) - 1 and end != -1:
            return raw[start:end].strip()
        return raw.strip()

    async def _resolve_model_group(self, chat_key: str = "") -> str:
        if config.MODEL_GROUP:
            return config.MODEL_GROUP
        if chat_key:
            channel = await DBChatChannel.get_or_none(chat_key=chat_key)
            if channel:
                cc = await channel.get_effective_config()
                if cc.USE_MODEL_GROUP:
                    return cc.USE_MODEL_GROUP
        return core_config.USE_MODEL_GROUP

    async def _chat(self, prompt: str, chat_key: str = "", temperature: float = 0.7) -> str:
        group_name = await self._resolve_model_group(chat_key)
        model_group = core_config.MODEL_GROUPS.get(group_name)
        if model_group is None:
            raise ValueError(f"LLM 模型组不存在：{group_name}")
        response = await gen_openai_chat_response(
            model=model_group.CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            base_url=model_group.BASE_URL,
            api_key=model_group.API_KEY,
            stream_mode=False,
        )
        return response.response_content or ""

    async def _get_msg_contexts(self, chat_key: str) -> list[dict[str, str]]:
        limit = int(self.cfg.source.post_max_msg)
        messages = await DBChatMessage.filter(chat_key=chat_key).exclude(sender_id="-1").order_by("-id").limit(limit)
        contexts: list[dict[str, str]] = []
        for msg in reversed(messages):
            text = (msg.content_text or "").strip()
            if not text:
                continue
            name = msg.sender_nickname or msg.sender_name or msg.sender_id
            contexts.append({"role": "user", "content": f"{name}: {text}"})
        return contexts

    async def generate_post(
        self,
        chat_key: str = "",
        topic: str | None = None,
        persona: str = "",
        use_chat_context: bool = True,
    ) -> str | None:
        """生成一条说说

        Args:
            chat_key: 聊天频道标识，用于解析模型组和（可选）参考聊天记录。
            topic: 自然语言写作主题。
            persona: 人设内容，为空则不注入人设。
            use_chat_context: 是否参考聊天记录生成内容。
        """
        contexts: list[dict[str, str]] = []
        transcript = ""
        if chat_key and use_chat_context:
            contexts = await self._get_msg_contexts(chat_key)
            transcript = "\n".join(c["content"] for c in contexts)

        parts: list[str] = []
        if persona:
            parts.append(f"# 你的人设：\n{persona}")
        parts.append(f"# 写作主题：{topic or '从聊天内容中选一个主题'}")
        if transcript:
            parts.append(f"# 聊天记录参考：\n{transcript}")
        parts.extend(
            [
                self.cfg.llm.post_prompt,
                "# 输出格式要求：\n"
                '- 使用三对双引号（"""）将正文内容包裹起来。\n'
                "- 只输出最终可发布的说说正文，不要附带解释、标题或额外说明。",
            ]
        )
        prompt = self._join_prompt_parts(*parts)
        try:
            raw = await self._chat(prompt, chat_key=chat_key, temperature=0.9)
            text = self.extract_content(raw)
            if not text:
                raise ValueError("LLM 生成的说说为空")
            logger.info(f"LLM 生成的说说：{text}")
            return text
        except Exception as e:
            raise ValueError(f"LLM 调用失败：{e}") from e

    async def generate_comment(self, post: Post, chat_key: str = "") -> str | None:
        """根据帖子内容生成评论"""
        content = post.text
        if post.rt_con:
            content += f"\n[转发]\n{post.rt_con}"
        prompt = self._join_prompt_parts(
            self.cfg.llm.comment_prompt,
            "# 输出要求：\n- 只输出最终评论内容，不要解释，不要分点，不要添加额外前缀。",
            f"\n[帖子内容]：\n{content}",
        )
        try:
            raw = await self._chat(prompt, chat_key=chat_key, temperature=0.8)
            comment = re.sub(r"[\s\u3000]+", "", raw).rstrip("。")
            logger.info(f"LLM 生成的评论：{comment}")
            return comment
        except Exception as e:
            raise ValueError(f"LLM 调用失败：{e}") from e
