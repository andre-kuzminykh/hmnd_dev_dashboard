"""Connectors to external APIs (OpenAI, Anthropic, GitHub).

Каждый коннектор соответствует FR-09.1.1.1: интерфейс
`test_connection() -> bool`, `sync(period) -> SyncReport`.
В режиме mock=True возвращаются seed-данные без сетевых вызовов.
"""
from .base import BaseConnector, SyncReport
from .openai import OpenAIConnector
from .anthropic import AnthropicConnector
from .github import GitHubConnector

__all__ = [
    "BaseConnector",
    "SyncReport",
    "OpenAIConnector",
    "AnthropicConnector",
    "GitHubConnector",
]
