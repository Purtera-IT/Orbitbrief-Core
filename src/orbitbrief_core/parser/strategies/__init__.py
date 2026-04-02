"""Discourse strategy implementations for parser runtime."""

from .base import BaseStrategy, StrategyContext, StrategyError
from .call_transcript import CallTranscriptStrategy
from .conversation import ConversationStrategy
from .email_thread import EmailThreadStrategy
from .hybrid import HybridStrategy
from .meeting_notes import MeetingNotesStrategy
from .project_memo import ProjectMemoStrategy

__all__ = [
    "BaseStrategy",
    "StrategyContext",
    "StrategyError",
    "CallTranscriptStrategy",
    "MeetingNotesStrategy",
    "ConversationStrategy",
    "EmailThreadStrategy",
    "ProjectMemoStrategy",
    "HybridStrategy",
]
