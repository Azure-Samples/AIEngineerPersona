"""
ApprovalGatewayExecutor — Type-safe pass-through between Decision and bonus agents.

DecisionExecutor outputs two message types:
  • StoryResponse  (approved path → flows to bonus agents / final assembly)
  • RevisionSignal (rejected path → loops back to OrchestratorExecutor)

The agent_framework type validator checks that ALL output types of a source
executor are compatible with every target executor's input types.  That means
we cannot wire Decision directly to the bonus agents because RevisionSignal is
not handled by LookAndFindActivityExecutor or CharacterGlossaryExecutor.

ApprovalGatewayExecutor acts as a single-type funnel:
  Decision ──StoryResponse──► ApprovalGateway ──StoryResponse──► bonus agents

Because ApprovalGateway only handles StoryResponse, the edge from Decision to
ApprovalGateway is also type-safe (Decision does output StoryResponse).
"""

import logging

from agent_framework import Executor, WorkflowContext, handler

from ..models import StoryResponse

logger = logging.getLogger(__name__)


class ApprovalGatewayExecutor(Executor):
    """
    Receives the approved StoryResponse from DecisionExecutor and forwards it
    unchanged to the next node(s) in the graph (bonus agents or final assembly).
    """

    def __init__(self) -> None:
        super().__init__(id="approval_gateway")

    @handler
    async def handle_approved_story(
        self,
        story: StoryResponse,
        ctx: WorkflowContext[StoryResponse],
    ) -> None:
        logger.info(
            "[ApprovalGateway] Forwarding approved story '%s' to bonus agents.",
            story.title,
        )
        await ctx.send_message(story)
