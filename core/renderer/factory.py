from __future__ import annotations

from ..config import PluginConfig
from .builtin_renderer import BuiltinQzoneCardRenderer
from .protocol import MessageRenderer


def create_message_renderer(config: PluginConfig) -> MessageRenderer:
    return BuiltinQzoneCardRenderer(config)