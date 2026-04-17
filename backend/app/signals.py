from dataclasses import dataclass
from typing import Optional
from pydantic import BaseModel, Field

from .models import (
    StoryRequest,
    StoryOutline,
    StoryDraft,
    ReviewResult,
    StoryResponse,
    ProgressEvent,
)


# Lightweight signal sent from DecisionExecutor back to OrchestratorExecutor
@dataclass
class RevisionSignal:
    """Signals the Orchestrator to rebuild the outline using reviewer feedback."""
    revision_instructions: str
    revision_round: int
