"""
Foundry agent registry + startup validator.

This module owns the canonical list of agent NAMES that the app expects to
find in the Foundry project when AGENT_HOSTING_MODE=foundry. It provides
two things:

1. `EXPECTED_FOUNDRY_AGENT_NAMES` — the single source of truth for which
   names need to exist. Imported by both the runtime startup validator and
   the provisioning script so drift between them is impossible.

2. `validate_foundry_agents()` — a coroutine called from the FastAPI
   lifespan hook (only when mode=foundry) that lists the project's
   agents once and asserts every expected name resolves to **exactly
   one** agent. Foundry permits multiple agents with the same display
   name; lookup-by-name is therefore ambiguous if duplicates exist, so
   we fail loudly at boot rather than nondeterministically resolve to
   the wrong agent at request time.

The validator is intentionally separate from the storage init startup
hook because the storage init catches and logs errors to keep the app
serving; this validator MUST crash the process.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential

from .config import settings

logger = logging.getLogger(__name__)


# The canonical set of agent names expected to exist in the Foundry project
# when AGENT_HOSTING_MODE=foundry. Keep this in lock-step with:
#   - the names passed to `build_chat_agent(name=..., ...)` in each agent module
#   - the AGENTS manifest in `app.scripts.provision_foundry_agents`
EXPECTED_FOUNDRY_AGENT_NAMES: list[str] = [
    "OrchestratorAgent",
    "StoryArchitectAgent",
    "PerPageReviewerAgent",
    "CoverReviewerAgent",
    "TheEndReviewerAgent",
    "StoryTextReviewerAgent",
    "CrossPageConsistencyAgent",
    "LookAndFindActivityAgent",
    "CharacterGlossaryAgent",
    "StorySuggestionAgent",
]


PROVISIONING_HINT = (
    "Run the provisioning script to create them:\n"
    "    cd backend && python -m app.scripts.provision_foundry_agents\n"
    "Or use --dry-run first to preview actions without applying them."
)


class FoundryAgentValidationError(RuntimeError):
    """Raised when the Foundry project doesn't satisfy our agent contract.

    Subclasses RuntimeError so an uncaught instance crashes the FastAPI
    process, which is the desired fast-fail UX in foundry mode.
    """


async def validate_foundry_agents(
    *, expected_names: list[str] | None = None
) -> None:
    """List Foundry agents once; assert each expected name resolves uniquely.

    Args:
        expected_names: Override the default `EXPECTED_FOUNDRY_AGENT_NAMES`
            list. Mostly for tests; production callers should rely on the
            default.

    Raises:
        FoundryAgentValidationError: If any expected agent name is missing
            (count == 0) or duplicated (count > 1) in the project.
    """
    # Imported lazily so the local-mode path doesn't pay the import cost
    # (and the local-mode test/dev install can omit `azure-ai-projects` if
    # it ever becomes optional).
    from azure.ai.projects.aio import AIProjectClient

    if not settings.foundry_project_endpoint:
        raise FoundryAgentValidationError(
            "AGENT_HOSTING_MODE=foundry requires FOUNDRY_PROJECT_ENDPOINT to be set."
        )
    if not settings.foundry_project_name:
        raise FoundryAgentValidationError(
            "AGENT_HOSTING_MODE=foundry requires FOUNDRY_PROJECT_NAME to be set "
            "(the project under FOUNDRY_PROJECT_ENDPOINT). See "
            "docs/09-guide-foundry-hosted-agents.md."
        )

    expected = expected_names if expected_names is not None else EXPECTED_FOUNDRY_AGENT_NAMES
    expected_set = set(expected)

    name_to_agents: dict[str, list[object]] = defaultdict(list)

    async with AsyncDefaultAzureCredential() as credential:
        async with AIProjectClient(
            endpoint=settings.foundry_agents_endpoint,
            credential=credential,
        ) as project:
            async for agent in project.agents.list():
                # We only care about agents whose names we expect; no need
                # to bucket the entire project's catalogue.
                if agent.name in expected_set:
                    name_to_agents[agent.name].append(agent)

    missing: list[str] = []
    duplicated: list[tuple[str, int]] = []
    for name in expected:
        count = len(name_to_agents.get(name, []))
        if count == 0:
            missing.append(name)
        elif count > 1:
            duplicated.append((name, count))

    if missing or duplicated:
        msg_parts: list[str] = [
            "Foundry agent validation failed for project "
            f"{settings.foundry_agents_endpoint!r}."
        ]
        if missing:
            msg_parts.append(
                f"Missing agents ({len(missing)}): {', '.join(missing)}"
            )
        if duplicated:
            msg_parts.append(
                "Duplicate-name agents (lookup-by-name is ambiguous): "
                + ", ".join(f"{n} (×{c})" for n, c in duplicated)
            )
        msg_parts.append(PROVISIONING_HINT)
        raise FoundryAgentValidationError("\n".join(msg_parts))

    logger.info(
        "Foundry agent validation OK — all %d expected agents resolved uniquely.",
        len(expected),
    )
