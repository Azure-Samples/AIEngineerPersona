"""
Agent factory — single seam for swapping between locally-constructed agents
(via OpenAIChatClient → Azure OpenAI / Foundry chat completions) and
Foundry-hosted agents (via FoundryAgent → AIProjectClient).

Selected by `settings.agent_hosting_mode`:

    local    — returns Agent(client=OpenAIChatClient(...), instructions=..., name=...)
               This is the prior in-process behaviour. Instructions in
               prompts.py are the source of truth.

    foundry  — returns FoundryAgent(project_endpoint=..., agent_name=name,
                                    credential=DefaultAzureCredential())
               The agent definition deployed in Foundry is the source of
               truth; we deliberately do NOT pass `instructions=` to
               FoundryAgent so any drift between prompts.py and the
               deployed agent is impossible from the runtime side. Re-run
               `python -m app.scripts.provision_foundry_agents` to push
               local prompts.py changes to the Foundry-deployed agents.

Construction is non-networking in both modes; FoundryAgent does its
name → agent resolution lazily on the first `.run()` call. The startup
validator in `foundry_agents.validate_foundry_agents` provides the fast-
fail UX so missing/duplicate names are caught at boot rather than on the
first user request.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from agent_framework import Agent, AgentResponse
from agent_framework.openai import OpenAIChatClient
from azure.identity import DefaultAzureCredential
from pydantic import BaseModel

from .config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def build_chat_agent(*, name: str, instructions: str) -> Agent:
    """Build a chat-capable Agent for the configured hosting mode.

    Args:
        name: The agent's name. In `local` mode this is the display name on
            the in-process Agent. In `foundry` mode this is the lookup key
            used to resolve the Foundry agent (must match what was
            written by `provision_foundry_agents`).
        instructions: System instructions. Used as the only source in
            `local` mode. **Ignored** in `foundry` mode — the deployed
            Foundry agent's instructions are canonical there.

    Returns:
        An Agent ready to call via `.run(...)`. The same `.run()` call
        site works in both modes.
    """
    mode = settings.agent_hosting_mode

    if mode == "local":
        return Agent(
            client=OpenAIChatClient(
                model=settings.foundry_model_deployment_name,
                azure_endpoint=settings.foundry_project_endpoint,
                credential=DefaultAzureCredential(),
            ),
            instructions=instructions,
            name=name,
        )

    if mode == "foundry":
        # Imported lazily so installations that never use foundry mode
        # don't pay the import cost (and don't crash if azure-ai-projects
        # transitives ever become optional).
        from agent_framework.foundry import FoundryAgent

        endpoint = settings.foundry_agents_endpoint
        if not endpoint:
            raise RuntimeError(
                "AGENT_HOSTING_MODE=foundry requires both FOUNDRY_PROJECT_ENDPOINT "
                "(account-level) and FOUNDRY_PROJECT_NAME (project under that "
                "account). Set FOUNDRY_PROJECT_NAME in .env — see "
                "docs/09-guide-foundry-hosted-agents.md."
            )
        return FoundryAgent(
            project_endpoint=endpoint,
            agent_name=name,
            credential=DefaultAzureCredential(),
        )

    raise ValueError(
        f"Unknown AGENT_HOSTING_MODE={mode!r}. Expected 'local' or 'foundry'."
    )


async def run_structured(
    agent: Agent,
    prompt: Any,
    *,
    response_format: type[T],
    **call_options: Any,
) -> tuple[AgentResponse, T]:
    """Run ``agent`` with structured-output parsing in a mode-agnostic way.

    In ``local`` mode this is a thin wrapper that passes
    ``response_format=`` through to ``agent.run`` — the underlying
    OpenAIChatClient renders it into the Responses-API ``text.format`` block
    on the request, exactly as before.

    In ``foundry`` mode the JSON schema MUST already be baked into the
    Foundry agent definition (the provisioning script does this). Foundry
    rejects per-call ``text.format`` payloads when an agent_name is set
    (HTTP 400 ``Not allowed when agent is specified. param: 'text'``), so
    we deliberately do NOT forward ``response_format`` to the Foundry
    SDK. The agent itself constrains the output shape; we just
    ``model_validate_json`` the raw text on the way out.

    Returns ``(raw_response, parsed_value)`` so callers retain access to
    usage telemetry on the response.
    """
    options: dict[str, Any] = dict(call_options)

    if settings.agent_hosting_mode == "foundry":
        # The bake-in happens at provisioning time; do NOT pass
        # response_format here or Foundry will 400.
        result = await agent.run(prompt, options=options or None)
        try:
            parsed = response_format.model_validate_json(result.text)
        except Exception as exc:  # pragma: no cover - re-raised with context
            text = result.text or ""
            head = text[:300]
            tail = text[-300:] if len(text) > 600 else ""
            raise RuntimeError(
                f"Foundry-hosted agent {agent.name!r} returned text that did not "
                f"match {response_format.__name__} (raw length={len(text)} chars). "
                "Make sure the agent was provisioned via "
                "`python -m app.scripts.provision_foundry_agents` with a current "
                f"schema. Underlying error: {type(exc).__name__}: {exc}. "
                f"Raw head: {head!r}"
                + (f" ... raw tail: {tail!r}" if tail else "")
            ) from exc
        return result, parsed

    # Local mode — preserve historical behaviour. response_format last so it
    # cannot be silently overridden by **call_options.
    options["response_format"] = response_format
    result = await agent.run(prompt, options=options)
    return result, result.value
