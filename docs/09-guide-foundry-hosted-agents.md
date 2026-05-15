# Guide: Hosting the Agents in Microsoft Foundry

[← Back to README](../README.md) | [Prerequisites & Setup](01-prerequisites-and-setup.md) | [Architecture Overview](02-architecture-overview.md)

This guide walks you through running the app's chat agents as **Microsoft Foundry-hosted agents** instead of as in-process LLM calls. With a single environment-variable flip, every agent in the workflow (orchestrator, story architect, the five reviewer sub-agents, the two activity-page agents, and the "Surprise Me" suggestion service) is resolved against an agent definition that lives in your Foundry project.

This is the prerequisite for [Guide: Running Cloud Evals in Microsoft Foundry](10.b-guide-evals-foundry.md), which evaluates those hosted agents end-to-end.

---

## Table of Contents

- [Why host the agents in Foundry?](#why-host-the-agents-in-foundry)
- [The two modes](#the-two-modes)
- [Source-of-truth contract (read this!)](#source-of-truth-contract-read-this)
- [Prerequisites](#prerequisites)
- [Step 1 — Provision the agents](#step-1--provision-the-agents)
- [Step 2 — Switch the app to Foundry mode](#step-2--switch-the-app-to-foundry-mode)
- [Step 3 — Verify](#step-3--verify)
- [Updating prompts after they're deployed](#updating-prompts-after-theyre-deployed)
- [The 10 hosted agents](#the-10-hosted-agents)
- [Configuration reference](#configuration-reference)
- [Troubleshooting](#troubleshooting)

---

## Why host the agents in Foundry?

The default `local` mode constructs each agent in-process via `OpenAIChatClient` pointed at your Foundry/Azure OpenAI deployment. That's fast to iterate on and requires no extra setup, but it means:

- The agent's instructions live only in your repo.
- Foundry's portal-side observability (per-agent traces, evaluation runs, version history) doesn't apply because Foundry never sees an "agent" — just chat-completion calls.
- You can't run portal evaluations against your agents.

Switching to `foundry` mode resolves each runtime call to a **named agent definition stored in your Foundry project**. From then on, Foundry's portal sees every invocation as belonging to a specific agent, which unlocks per-agent eval runs, version comparisons, and portal-managed prompt tweaks.

---

## The two modes

The `AGENT_HOSTING_MODE` setting in `backend/.env` selects the mode:

| Mode | What happens at runtime |
|---|---|
| **`local`** *(default)* | Every `build_chat_agent(name=…, instructions=…)` call constructs an in-process `Agent(client=OpenAIChatClient(…), instructions=…, name=…)`. The instructions in `prompts.py` are the only thing that drives behaviour. |
| **`foundry`** | Every `build_chat_agent(name=…, instructions=…)` call constructs a `FoundryAgent(project_endpoint=…, agent_name=name, …)`. **The `instructions=` argument is ignored** — the agent definition deployed in Foundry is what runs. |

The mode is selected once at startup and applies to the whole process. To switch back to local mode, unset `AGENT_HOSTING_MODE` (or set it to `local`) and restart the backend; nothing else needs to change.

---

## Source-of-truth contract (read this!)

This is the single most important thing to internalise before turning Foundry mode on:

> **In `local` mode, `prompts.py` is the source of truth.**
> **In `foundry` mode, the agent definition deployed in Foundry is the source of truth.**

The provisioning script (Step 1 below) is the **only** thing that pushes `prompts.py` strings into Foundry. After that:

- You can tweak prompts in `prompts.py` all day — but until you re-run `python -m app.scripts.provision_foundry_agents`, nothing changes for users in `foundry` mode.
- You can edit an agent's instructions directly in the Foundry portal (e.g., for an A/B test) — and as long as you don't re-run the provisioning script, your edit will stick.

This is intentional. Auto-syncing on every backend startup would silently overwrite portal-side edits, which is exactly the wrong behaviour during eval/experimentation work. The script is the user-driven sync point.

The same contract is reinforced in [Guide: Running Cloud Evals in Microsoft Foundry](10.b-guide-evals-foundry.md) because eval-driven prompt iteration is where it matters most.

---

## Prerequisites

- The backend can already run in `local` mode (i.e. you've completed [Prerequisites & Setup](01-prerequisites-and-setup.md) and the [Local Quickstart](00-local-quickstart.md)).
- Your `.env` already points at a Foundry project:
  - `FOUNDRY_PROJECT_ENDPOINT` is set (the **short**, account-level form: `https://<account>.services.ai.azure.com/`)
  - `FOUNDRY_PROJECT_NAME` is set (the project under that account; visible in the Foundry portal under **Overview → Project name**). The provisioning script and the runtime agent-lookup APIs need the long, project-scoped URL (`<endpoint>/api/projects/<name>`); supplying this name lets the app derive it without you having to maintain two endpoint URLs.
  - `FOUNDRY_MODEL_DEPLOYMENT_NAME` points at a chat-capable deployment in that project (e.g. `gpt-4o`, `gpt-5.4`)
- You're signed in to Azure on the workstation that will run the provisioning script:

  ```bash
  az login
  ```

- The signed-in user (or service principal) has at least the **Azure AI Developer** role on the Foundry project. Without this, the provisioning script can authenticate but cannot create agents.

> **Already deployed to Azure?** The container app's managed identity is already granted **Azure AI User** on the Foundry account by `infra/main-rg.bicep`, which is sufficient to *use* the hosted agents at runtime. You only need the Developer role on the workstation that runs the provisioning script.

---

## Step 1 — Provision the agents

From the `backend/` directory with your venv active:

```bash
# Preview what the script would do without changing anything
python -m app.scripts.provision_foundry_agents --dry-run

# Apply for real
python -m app.scripts.provision_foundry_agents
```

The script:

1. Lists every agent in the project once.
2. For each of the [10 agents we expect](#the-10-hosted-agents), decides one of:

   | Status | What it means |
   |---|---|
   | `created` | Agent didn't exist; it was created at version 1. |
   | `ok` | Agent exists and its model + instructions match what's in `prompts.py`. No-op. |
   | `updated` | Agent exists, model matches, but instructions drifted from `prompts.py` — a new version was pushed. |
   | `recreated` | (Only with `--recreate`) Agent was deleted and re-created. |
   | `model-drift` | Agent exists but its model differs from `FOUNDRY_MODEL_DEPLOYMENT_NAME`. **The script does NOT auto-update model**; re-run with `--recreate` once you've decided that's what you want. |
   | `duplicate` | More than one agent with this name exists in the project. Lookup-by-name is ambiguous; resolve in the portal (delete the dupe). |
   | `error` | Per-agent exception; see the stack trace above the table. |

3. Prints a status table.
4. Exits non-zero if any agent ended in `model-drift`, `duplicate`, or `error`. CI-friendly.

Example output of a clean first run:

```
─────────────────────────────────────────────────────────────────────
AGENT                       STATUS    ACTION
─────────────────────────────────────────────────────────────────────
OrchestratorAgent           created   create 'OrchestratorAgent' version 1 with model='gpt-5.4'
StoryArchitectAgent         created   create 'StoryArchitectAgent' version 1 with model='gpt-5.4'
PerPageReviewerAgent        created   …
…
StorySuggestionAgent        created   …
─────────────────────────────────────────────────────────────────────
Provisioning complete.
```

Subsequent runs (with no prompt changes) print all `ok` and exit immediately.

---

## Step 2 — Switch the app to Foundry mode

Edit `backend/.env` and set:

```env
AGENT_HOSTING_MODE=foundry
```

Optional: lower the reviewer fan-out cap to give Foundry's per-call thread/session creation some headroom under quota pressure (the default is `3`, vs. local mode's `5`):

```env
FOUNDRY_REVIEWER_MAX_CONCURRENT_CALLS=3
```

Restart the backend. On startup the app validates that every expected agent name resolves to **exactly one** agent in the project. If any are missing or duplicated, the process exits with a message that names the offenders and prints the provisioning command:

```
RuntimeError: Foundry agent validation failed for project '…'.
Missing agents (1): StorySuggestionAgent
Run the provisioning script to create them:
    cd backend && python -m app.scripts.provision_foundry_agents
```

This fast-fail is intentional. Discovering "wait, that agent name doesn't exist" on the first user request is a much worse experience than crashing on boot.

---

## Step 3 — Verify

1. Run the backend and frontend (see [Local Quickstart](00-local-quickstart.md)).
2. Generate a story with the reviewer enabled. Watch the backend logs — every `[Reviewer]`, `[Orchestrator]`, etc. line should look exactly the same as in `local` mode.
3. Open the Foundry portal → your project → **Tracing** (or **Threads**). You should see invocations grouped per agent name.
4. Click into an invocation to see the full prompt + response, the agent version that handled it, and the latency.

If the story finishes with `event: complete` and the portal shows traces under each agent name, you're done.

---

## Updating prompts after they're deployed

When you change a prompt in `prompts.py` and want Foundry runtime to follow:

```bash
cd backend
python -m app.scripts.provision_foundry_agents
```

The script detects the drift, calls `agents.create_version(...)` on the affected agent(s), and reports them as `updated`. Subsequent runtime calls in `foundry` mode resolve to the new version automatically (Foundry returns the latest version when you don't pin one).

If you've changed the **model** (`FOUNDRY_MODEL_DEPLOYMENT_NAME`), the script reports `model-drift` and refuses to silently swap the model on you. Re-run with `--recreate` once you're sure:

```bash
python -m app.scripts.provision_foundry_agents --recreate
```

`--recreate` deletes every existing agent in the manifest and re-creates it at version 1 with the new model. Use sparingly — version history is lost.

---

## The 10 hosted agents

These are all created by the provisioning script. Their names match what `build_chat_agent(name=…)` passes at runtime, so renaming them in the portal will break runtime resolution. (The validator catches this at boot.)

| Name | Role | Source of instructions |
|---|---|---|
| `OrchestratorAgent` | Builds the initial outline; revises it from reviewer feedback. | `ORCHESTRATOR_INSTRUCTIONS` in `prompts.py` |
| `StoryArchitectAgent` | Writes the full per-page text + image prompts. | `STORY_ARCHITECT_INSTRUCTIONS` |
| `PerPageReviewerAgent` | Reviews one page at a time (text + one image). | `PER_PAGE_REVIEWER_INSTRUCTIONS` |
| `CoverReviewerAgent` | Reviews the cover image only. | `COVER_REVIEWER_INSTRUCTIONS` |
| `TheEndReviewerAgent` | Reviews the "The End" page only. | `THE_END_REVIEWER_INSTRUCTIONS` |
| `StoryTextReviewerAgent` | Reviews narrative text without seeing the images. | `STORY_TEXT_REVIEWER_INSTRUCTIONS` |
| `CrossPageConsistencyAgent` | Checks character consistency across all pages. | `CROSS_PAGE_CONSISTENCY_INSTRUCTIONS` |
| `LookAndFindActivityAgent` | Picks 3–5 items for the Look & Find activity page. | `LOOK_AND_FIND_INSTRUCTIONS` |
| `CharacterGlossaryAgent` | Writes the glossary entries for each character. | `CHARACTER_GLOSSARY_INSTRUCTIONS` |
| `StorySuggestionAgent` | Powers the "Surprise Me" auto-fill on the create-story form. | `STORY_SUGGESTION_INSTRUCTIONS` (in `suggestion.py`'s prompt module) |

`ArtDirector` is **not** in this list because it's an image-generation client, not a chat agent. It continues to call the image deployment directly in both modes.

---

## Configuration reference

| Setting | Default | When to change |
|---|---|---|
| `AGENT_HOSTING_MODE` | `local` | Set to `foundry` to use hosted agents. |
| `FOUNDRY_PROJECT_ENDPOINT` | (required) | Same value used in `local` mode — the **short** account-level URL. |
| `FOUNDRY_PROJECT_NAME` | (required in `foundry` mode) | The project under `FOUNDRY_PROJECT_ENDPOINT`. Used to build the long agent-management URL. |
| `FOUNDRY_MODEL_DEPLOYMENT_NAME` | (required) | The model the provisioning script will write into each agent's definition. |
| `FOUNDRY_REVIEWER_MAX_CONCURRENT_CALLS` | `3` | Cap for the reviewer fan-out semaphore in `foundry` mode. Lower if you're hitting Foundry rate limits; raise (cautiously) if you have plenty of quota. |
| `STORY_REVIEWER_MAX_CONCURRENT_CALLS` | `5` | Same cap, but for `local` mode. Foundry mode ignores this. |

---

## Troubleshooting

**"Foundry agent validation failed: Missing agents (…)" on backend startup.**
You enabled `AGENT_HOSTING_MODE=foundry` but haven't run the provisioning script yet (or it failed). Run `python -m app.scripts.provision_foundry_agents --dry-run` to see what's missing, then drop the `--dry-run` to apply.

**"Duplicate-name agents (…)".**
Foundry permits multiple agents with the same display name. Open the portal, find the duplicates, and delete the unwanted one(s). Then re-run the provisioning script (it'll be a no-op).

**"model-drift" status from the provisioning script.**
The agent in Foundry was created with a different model deployment than `FOUNDRY_MODEL_DEPLOYMENT_NAME`. The script is being conservative because changing the model is more invasive than changing instructions. Decide whether you really want to swap, then re-run with `--recreate`.

**The provisioning script fails with "AuthorizationFailed" / 403.**
The user you're signed in as (`az login`) doesn't have the **Azure AI Developer** role (or higher) on the Foundry project. Ask the project owner to grant it.

**The deployed container app fails on the first request to a hosted agent with 403.**
The container's managed identity needs **Azure AI User** on the Foundry account. `infra/main-rg.bicep` already provisions this when you deploy with `azd up`; if you bootstrapped a different way, grant it manually.

**I edited a prompt in the Foundry portal and now the next provisioning run is going to overwrite it.**
That's correct, and it's the source-of-truth contract working as designed. If you want to keep portal-side edits, don't re-run the script. If you want to bring those edits back into the repo, copy the new instructions into `prompts.py` first.

**My local-mode runs are unchanged but I want to be sure.**
That's the goal. `local` mode is the default — if `AGENT_HOSTING_MODE` is unset, the factory returns the same `Agent(client=OpenAIChatClient(…), instructions=…)` you had before this guide existed. Nothing about local mode's behaviour changes.
