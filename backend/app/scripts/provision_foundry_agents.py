"""
Idempotent provisioning script for the 10 Foundry-hosted chat agents the
app expects when AGENT_HOSTING_MODE=foundry.

Why a script (and not auto-bootstrap on every backend startup): the
agent definition deployed in Foundry is the source of truth at runtime
when AGENT_HOSTING_MODE=foundry (see docs/09-guide-foundry-hosted-agents.md
for the full source-of-truth contract). Auto-syncing on startup would
silently overwrite portal-side edits a user might have made for an
A/B test or eval; instead, this script is the sole, user-driven sync
point between `prompts.py` and the Foundry project.

Usage::

    cd backend
    python -m app.scripts.provision_foundry_agents              # apply
    python -m app.scripts.provision_foundry_agents --dry-run    # preview
    python -m app.scripts.provision_foundry_agents --recreate   # delete + recreate

Authentication uses ``DefaultAzureCredential`` — run ``az login`` first.
The user (or service principal) needs *Azure AI Developer* or higher on
the Foundry project to create/update/delete agents.

Status table printed at the end:

    created       — new agent created (version 1)
    ok            — agent exists and matches local prompt + model
    updated       — instructions changed locally, new version pushed
    recreated     — agent deleted and re-created (only with --recreate)
    model-drift   — model in Foundry differs from settings.foundry_model_deployment_name;
                    NOT auto-updated. Re-run with --recreate to fix.
    duplicate     — multiple agents with the same name exist in the project
                    (lookup-by-name is ambiguous). Resolve in the portal.
    error         — exception raised; see preceding stack trace.

Exit code is non-zero if any agent ends in {model-drift, duplicate, error}.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from typing import Any, Iterable

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentDetails,
    PromptAgentDefinition,
    PromptAgentDefinitionTextOptions,
    TextResponseFormatJsonSchema,
)
from azure.identity import DefaultAzureCredential
from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel

from ..config import settings
from ..foundry_agents import EXPECTED_FOUNDRY_AGENT_NAMES
from ..models import (
    CharacterGlossary,
    CrossPageConsistencyResult,
    LookAndFindActivity,
    PageReviewResult,
    StoryArchitectOutput,
    StoryOutlineDraft,
    StorySuggestion,
    StoryTextReviewResult,
)
from ..prompts import (
    CHARACTER_GLOSSARY_INSTRUCTIONS,
    COVER_REVIEWER_INSTRUCTIONS,
    CROSS_PAGE_CONSISTENCY_INSTRUCTIONS,
    LOOK_AND_FIND_INSTRUCTIONS,
    ORCHESTRATOR_INSTRUCTIONS,
    PER_PAGE_REVIEWER_INSTRUCTIONS,
    STORY_ARCHITECT_INSTRUCTIONS,
    STORY_SUGGESTION_INSTRUCTIONS,
    STORY_TEXT_REVIEWER_INSTRUCTIONS,
    THE_END_REVIEWER_INSTRUCTIONS,
)


logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("provision_foundry_agents")


# Manifest of (agent_name, instructions, response_format).
#
# ``response_format`` is the Pydantic model the runtime expects each agent to
# emit. We bake its JSON schema into the Foundry agent definition at
# provisioning time because Foundry rejects per-call ``text.format`` payloads
# (HTTP 400 ``Not allowed when agent is specified. param: 'text'``). The
# runtime's ``run_structured`` helper deliberately does NOT forward
# response_format to Foundry — the agent definition is the source of truth.
#
# Order is the order they'll be printed in the status table; keep grouped by
# role for readability. Names MUST exactly match
# EXPECTED_FOUNDRY_AGENT_NAMES (asserted below).
AGENTS: list[tuple[str, str, type[BaseModel]]] = [
    ("OrchestratorAgent",          ORCHESTRATOR_INSTRUCTIONS,           StoryOutlineDraft),
    ("StoryArchitectAgent",        STORY_ARCHITECT_INSTRUCTIONS,        StoryArchitectOutput),
    ("PerPageReviewerAgent",       PER_PAGE_REVIEWER_INSTRUCTIONS,      PageReviewResult),
    ("CoverReviewerAgent",         COVER_REVIEWER_INSTRUCTIONS,         PageReviewResult),
    ("TheEndReviewerAgent",        THE_END_REVIEWER_INSTRUCTIONS,       PageReviewResult),
    ("StoryTextReviewerAgent",     STORY_TEXT_REVIEWER_INSTRUCTIONS,    StoryTextReviewResult),
    ("CrossPageConsistencyAgent",  CROSS_PAGE_CONSISTENCY_INSTRUCTIONS, CrossPageConsistencyResult),
    ("LookAndFindActivityAgent",   LOOK_AND_FIND_INSTRUCTIONS,          LookAndFindActivity),
    ("CharacterGlossaryAgent",     CHARACTER_GLOSSARY_INSTRUCTIONS,     CharacterGlossary),
    ("StorySuggestionAgent",       STORY_SUGGESTION_INSTRUCTIONS,       StorySuggestion),
]

# Hard cross-check: keep manifest ↔ runtime validator in lock-step.
assert {n for n, _, _ in AGENTS} == set(EXPECTED_FOUNDRY_AGENT_NAMES), (
    "AGENTS manifest in provision_foundry_agents.py is out of sync with "
    "EXPECTED_FOUNDRY_AGENT_NAMES in foundry_agents.py — they must match."
)


# Status values that should fail the script.
_FAIL_STATUSES = {"duplicate", "model-drift", "error"}


def _build_text_options(response_format: type[BaseModel]) -> PromptAgentDefinitionTextOptions:
    """Build the Foundry text-format options for a Pydantic response model.

    Uses ``openai.lib._pydantic.to_strict_json_schema`` so the produced
    schema is the same one the OpenAI Responses API would have generated
    locally — i.e. with ``additionalProperties: false`` everywhere,
    nullable fields properly tagged, etc. Foundry's strict-mode validator
    enforces the same rules as OpenAI's.
    """
    return PromptAgentDefinitionTextOptions(
        format=TextResponseFormatJsonSchema(
            name=response_format.__name__,
            schema=to_strict_json_schema(response_format),
            strict=True,
        )
    )


def _build_definition(
    instructions: str,
    target_model: str,
    response_format: type[BaseModel],
) -> PromptAgentDefinition:
    """Construct the full PromptAgentDefinition we want Foundry to hold.

    Same call is used by both ``_decide_action`` (for drift detection)
    and ``_apply`` (for the actual create/update). Keeping a single
    definition factory avoids "decided to update because of a difference
    that we then didn't actually push" classes of bug.
    """
    return PromptAgentDefinition(
        model=target_model,
        instructions=instructions,
        text=_build_text_options(response_format),
    )


def _text_format_dict(definition: PromptAgentDefinition) -> dict[str, Any] | None:
    """Extract ``text.format`` as a dict for drift comparison, or None."""
    text = getattr(definition, "text", None)
    if text is None:
        return None
    fmt = getattr(text, "format", None)
    if fmt is None:
        return None
    return fmt.as_dict()


def _bucket_by_name(agents: Iterable[AgentDetails]) -> dict[str, list[AgentDetails]]:
    """Group existing agents by display name. Foundry permits duplicates; we
    must detect them rather than pick the first match nondeterministically."""
    out: dict[str, list[AgentDetails]] = defaultdict(list)
    for a in agents:
        out[a.name].append(a)
    return out


def _existing_definition(agent: AgentDetails) -> PromptAgentDefinition | None:
    """Pull the latest version's PromptAgentDefinition off an AgentDetails.

    Returns None if the agent isn't a prompt agent (e.g. hosted/workflow);
    we treat those as ineligible for in-place update and surface as `error`.
    """
    versions = getattr(agent, "versions", None)
    latest = getattr(versions, "latest", None) if versions else None
    if latest is None:
        return None
    definition = getattr(latest, "definition", None)
    if isinstance(definition, PromptAgentDefinition):
        return definition
    return None


def _decide_action(
    name: str,
    desired: PromptAgentDefinition,
    matches: list[AgentDetails],
    target_model: str,
    *,
    recreate: bool,
) -> tuple[str, str]:
    """Return (status, human_readable_action_description) for a single agent.

    Pure function — does NOT mutate Foundry state. The applier below is the
    only thing that performs side-effects, which keeps --dry-run trivially
    correct (same decision logic, no execution).
    """
    if recreate and len(matches) >= 1:
        return ("recreated", f"delete {len(matches)} agent(s) named {name!r}, then create version 1")

    if len(matches) == 0:
        return ("created", f"create {name!r} version 1 with model={target_model!r}")

    if len(matches) > 1:
        return (
            "duplicate",
            f"{len(matches)} agents named {name!r} exist — ambiguous; resolve in the portal or pass --recreate",
        )

    # Exactly one existing agent.
    existing_def = _existing_definition(matches[0])
    if existing_def is None:
        return (
            "error",
            f"{name!r} exists but isn't a prompt agent; resolve in the portal or pass --recreate",
        )

    existing_model = existing_def.model or ""
    existing_instructions = existing_def.instructions or ""

    if existing_model != target_model:
        return (
            "model-drift",
            (
                f"model in Foundry is {existing_model!r}, expected {target_model!r}. "
                "Re-run with --recreate to replace."
            ),
        )

    drifted: list[str] = []
    if existing_instructions != (desired.instructions or ""):
        drifted.append("instructions")
    if _text_format_dict(existing_def) != _text_format_dict(desired):
        drifted.append("response_format")

    if drifted:
        return ("updated", f"push new version of {name!r} with updated {', '.join(drifted)}")

    return ("ok", f"{name!r} is up-to-date")


def _apply(
    project: AIProjectClient,
    name: str,
    desired: PromptAgentDefinition,
    matches: list[AgentDetails],
    status: str,
) -> None:
    """Apply the decided action. Called only when --dry-run is NOT set and
    when the status is one we actually act on (created/updated/recreated)."""
    if status == "recreated":
        for existing in matches:
            project.agents.delete(existing.name)
        project.agents.create_version(name, definition=desired)
        return

    if status in ("created", "updated"):
        # create_version is the same call for both "first version of a new
        # agent" and "next version of an existing agent" — Foundry creates
        # the agent on first version write.
        project.agents.create_version(name, definition=desired)
        return

    # ok, duplicate, model-drift, error → no-op.


def _print_table(rows: list[tuple[str, str, str]]) -> None:
    """Pretty status grid printed to stdout (logger keeps stderr for diags)."""
    name_w = max(len(n) for n, _, _ in rows + [("AGENT", "", "")])
    status_w = max(len(s) for _, s, _ in rows + [("", "STATUS", "")])
    sep = "─" * (name_w + status_w + 60)
    print(sep)
    print(f"{'AGENT'.ljust(name_w)}  {'STATUS'.ljust(status_w)}  ACTION")
    print(sep)
    for n, s, a in rows:
        print(f"{n.ljust(name_w)}  {s.ljust(status_w)}  {a}")
    print(sep)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="provision_foundry_agents",
        description=(
            "Idempotently provision the chat agents this app uses when "
            "AGENT_HOSTING_MODE=foundry."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the actions that would be taken; do not modify Foundry.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help=(
            "Delete and recreate every existing agent in the manifest. Use this "
            "to fix model-drift or when the prompt structure has changed enough "
            "that a new version isn't appropriate."
        ),
    )
    args = parser.parse_args(argv)

    if not settings.foundry_project_endpoint:
        logger.error(
            "FOUNDRY_PROJECT_ENDPOINT is not set. Configure your .env file before running."
        )
        return 2

    if not settings.foundry_project_name:
        logger.error(
            "FOUNDRY_PROJECT_NAME is not set — required to address the project under "
            "the account at FOUNDRY_PROJECT_ENDPOINT. See docs/09-guide-foundry-hosted-agents.md."
        )
        return 2

    target_model = settings.foundry_model_deployment_name
    if not target_model:
        logger.error("FOUNDRY_MODEL_DEPLOYMENT_NAME is not set; cannot provision agents.")
        return 2

    agents_endpoint = settings.foundry_agents_endpoint
    logger.info(
        "Provisioning agents in project %s with model %r (dry-run=%s, recreate=%s)",
        agents_endpoint,
        target_model,
        args.dry_run,
        args.recreate,
    )

    rows: list[tuple[str, str, str]] = []  # (name, status, action)

    # Pre-build all desired definitions BEFORE any side-effects so a bad
    # schema or missing prompt fails fast and atomically — half-provisioning
    # the project and then crashing is much harder to recover from than
    # crashing before the first network call.
    try:
        desired_by_name: dict[str, PromptAgentDefinition] = {
            name: _build_definition(instructions, target_model, response_format)
            for name, instructions, response_format in AGENTS
        }
    except Exception:
        logger.exception("Failed to build agent definitions; aborting before any Foundry calls.")
        return 2

    with DefaultAzureCredential() as credential:
        with AIProjectClient(
            endpoint=agents_endpoint,
            credential=credential,
        ) as project:
            # Single list call up front so we don't pay one round-trip per
            # agent. Foundry doesn't support a `name=` filter on list, so we
            # fetch all and bucket client-side.
            existing_by_name = _bucket_by_name(project.agents.list())

            for name, _, _ in AGENTS:
                desired = desired_by_name[name]
                matches = existing_by_name.get(name, [])
                try:
                    status, action = _decide_action(
                        name, desired, matches, target_model, recreate=args.recreate
                    )
                    if not args.dry_run and status not in {"ok", "duplicate", "model-drift", "error"}:
                        _apply(project, name, desired, matches, status)
                except Exception as exc:  # noqa: BLE001 — surface every per-agent failure in the table
                    logger.exception("Failed to provision %s", name)
                    status = "error"
                    action = f"{type(exc).__name__}: {exc}"
                rows.append((name, status, action))

    _print_table(rows)

    failed = [n for n, s, _ in rows if s in _FAIL_STATUSES]
    if failed:
        logger.error("Provisioning finished with failures: %s", ", ".join(failed))
        return 1

    if args.dry_run:
        logger.info("Dry-run complete — no changes applied.")
    else:
        logger.info("Provisioning complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
