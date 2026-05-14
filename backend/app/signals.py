from dataclasses import dataclass, field
from typing import Optional
from pydantic import BaseModel, Field

from .models import (
    StoryRequest,
    StoryOutline,
    StoryDraft,
    ReviewResult,
    StoryResponse,
    ProgressEvent,
    ImageRevisionTarget,
)


# Lightweight signal sent from DecisionExecutor back to OrchestratorExecutor
@dataclass
class RevisionSignal:
    """Signals the Orchestrator to rebuild the outline using reviewer feedback."""
    revision_instructions: str
    revision_round: int


# Signal sent from DecisionExecutor → ArtDirectorExecutor for image-only
# revisions. ArtDirector regenerates ONLY the slots listed in `targets`
# (leaving every other page's existing image_url intact) and then re-emits
# the updated StoryDraft so the workflow continues into the reviewer.
@dataclass
class ImageRevisionSignal:
    revision_round: int
    targets: list[ImageRevisionTarget] = field(default_factory=list)
