# Guide: Adding Activity Page Agents

[← Back to README](../README.md) | [Prerequisites & Setup](01-prerequisites-and-setup.md) | [Architecture Overview](02-architecture-overview.md)

This step-by-step guide walks you through extending the Children's Story Studio workflow with two new agents — a **Look & Find Activity** page generator and a **Character Glossary** page generator — using **GitHub Copilot** to plan and implement the changes.

---

## Table of Contents

- [What You'll Build](#what-youll-build)
- [Why This Matters](#why-this-matters)
- [Before You Start](#before-you-start)
- [Step 1: Plan the Implementation (Plan Mode + Claude Opus)](#step-1-plan-the-implementation-plan-mode--claude-opus)
- [Step 2: Implement with GitHub Copilot (Agent Mode + Claude Sonnet)](#step-2-implement-with-github-copilot-agent-mode--claude-sonnet)
- [Step 3: Review and Test](#step-3-review-and-test)
- [What to Look For](#what-to-look-for)
- [Reference Branch](#reference-branch)
- [Troubleshooting](#troubleshooting)

---

## What You'll Build

By the end of this guide, your storybook will include two optional activity pages that appear after the story:

1. **Look & Find Activity Page** — A children's activity that challenges the reader to find 3–5 specific items from the story's illustrations on various pages. The agent examines the generated images and picks items for the child to search for.

2. **Character Glossary Page** — A reference page listing all characters from the story along with a short description of each character.

Both pages are **opt-in** — the user can enable or disable each one via checkboxes on the Story Form.

<!-- TODO: Add screenshot of the completed storybook with activity pages -->

### Updated Workflow

The modified workflow uses the Agent Framework's **fan-out / fan-in** pattern to run both new agents in parallel after the story has been approved:

```
                              StoryRequest
                                   │
                                   ▼
                            ┌──────────────┐
                            │  Orchestrator │ ◄── RevisionSignal
                            └──────┬───────┘           ▲
                                   ▼                   │
                            ┌──────────────┐           │
                            │StoryArchitect│           │
                            └──────┬───────┘           │
                                   ▼                   │
                            ┌──────────────┐           │
                            │  ArtDirector │           │
                            └──────┬───────┘           │
                                   ▼                   │
                            ┌──────────────┐           │
                            │StoryReviewer │           │
                            └──────┬───────┘           │
                                   ▼                   │
                            ┌──────────────┐           │
                            │   Decision   │ ──────────┘
                            └──────┬───────┘
                                   │ (approved)
                          ┌────────┴────────┐
                          ▼                 ▼
                 ┌─────────────┐   ┌────────────────┐
                 │ LookAndFind │   │ CharGlossary   │
                 │   Agent     │   │    Agent        │
                 └──────┬──────┘   └───────┬────────┘
                        └────────┬─────────┘
                                 ▼
                          Final Output
                      (Story + Activities)
```

---

## Why This Matters

This guide demonstrates several important Agent Framework patterns:

| Pattern | What It Shows |
|---|---|
| **Fan-out / Fan-in** | How to execute multiple agents in parallel after a common predecessor, then merge their results |
| **New Agent Creation** | How to author new agents and integrate them into an existing workflow |
| **Conditional Workflow Paths** | How to dynamically include or exclude agents based on user input |
| **UI Extension** | How to modify the frontend to support new workflow capabilities |
| **Copilot-Driven Development** | How GitHub Copilot can plan and implement multi-file changes across a full-stack application |

---

## Before You Start

1. **Complete all prerequisites** from [Prerequisites & Setup](01-prerequisites-and-setup.md).

2. **Ensure the base application works** — Follow [Running the Demo](03-running-the-demo.md) and generate at least one story successfully.

3. **Verify VS Code extensions are installed and enabled:**
   - [ ] **GitHub Copilot** and **GitHub Copilot Chat** — installed and signed in
   - [ ] **VS Code AI Toolkit** — installed and enabled
   - [ ] **Context7 MCP server** — configured and enabled in your VS Code MCP settings

4. **Ensure you're on the `main` branch:**
   ```bash
   git checkout main
   git pull origin main
   ```

5. **(Recommended) Create a working branch:**
   ```bash
   git checkout -b my-activity-pages
   ```

---

## Step 1: Plan the Implementation (Plan Mode + Claude Opus)

In this step, you'll use GitHub Copilot's **Plan mode** with **Claude Opus** (or your preferred model) to analyze the codebase and produce a detailed implementation plan — without making any code changes.

### 1.1 Open GitHub Copilot Chat

- Open the **Copilot Chat** panel in VS Code (click the Copilot icon in the sidebar, or press `Ctrl+Shift+I` / `Cmd+Shift+I`).

### 1.2 Switch to Plan Mode

- At the top of the Copilot Chat panel, switch the mode from **"Ask"** or **"Agent"** to **"Plan"**.

<!-- TODO: Add screenshot showing the Plan mode selector in Copilot Chat -->

### 1.3 Select Claude Opus as the Model

- Click the model selector (usually shows the current model name) and choose **Claude Opus** (or your preferred model).
- Claude Opus excels at analyzing complex codebases and producing thorough, well-structured plans.

<!-- TODO: Add screenshot showing the model selector with Claude Opus selected -->

### 1.4 Paste the Sample Prompt

Copy and paste the following prompt into the Copilot Chat input:

> **Prompt:**
>
> Adjust the Agent Framework workflow to fan out to two additional agents after the story has received final approval. Utilize the `.add_fan_out_edges()`/`.add_fan_in_edges()` functionality within Agent Framework. ENSURE that all source and target executors are compatible with each other. Add all executors necessary to make a proper transition to using these additional agents. Also, be sure to make proper adjustments to the UI. The StoryForm functionality should be adjusted to have two additional checkboxes for enabling the creation of the Look & Find activity page and the Character Glossary page.
>
> Agents:
> - The first agent should be named LookAndFindActivityAgent. The LookAndFindActivityAgent will be responsible for adding a children's activity page to the end of the book that will challenge the child to find items on various pages. This agent should receive the images that have been generated as input and pick 3-5 items off of various pages for the child to search for.
> - The second agent should be named the CharacterGlossaryAgent. This agent is responsible for generating a page at the end of the book that lists out the characters in the book and provides a short description of the character. Adjust the StoryForm page to include two checkboxes for enabling or disabling both of these agents. Title each checkbox something like "Generate Look & Find Activity Page" and "Generate Character Glossary". The workflow generated should execute these agents additionally based on this selection. Also, make sure to update the ProgressTracker to include these agents if they are going to execute as a part of the workflow.

### 1.5 Review the Plan

Copilot (in Plan mode) will analyze the entire codebase and produce a detailed plan covering:

- **New files to create** — agent files for LookAndFindActivityAgent and CharacterGlossaryAgent
- **Existing files to modify** — workflow.py (fan-out/fan-in edges), models.py (new data models), StoryForm.jsx (checkboxes), ProgressTracker.jsx (new agent steps), StoryBook.jsx and StoryPage.jsx (new page types), and more
- **API changes** — how the new checkboxes will be passed from the frontend to the backend
- **Workflow changes** — how `add_fan_out_edges()` and `add_fan_in_edges()` will be used

**Take time to review the plan carefully.** Ask follow-up questions if anything is unclear:

- *"How will the fan-out edges work with the existing Decision executor?"*
- *"What data model changes are needed for the activity pages?"*
- *"How will the ProgressTracker know whether to show the new agents?"*

> **Experiment:** Try refining the prompt or asking Copilot to reconsider specific aspects of the plan. For example:
> - *"Can you reconsider how the Look & Find agent accesses the generated images?"*
> - *"What if both new agents are disabled — does the workflow still complete correctly?"*

---

## Step 2: Implement with GitHub Copilot (Agent Mode + Claude Sonnet)

Once you're satisfied with the plan, switch to **Agent mode** to let Copilot implement the changes.

### 2.1 Switch to Agent Mode

- Change the mode at the bottom of the Copilot Chat panel from **"Plan"** to **"Agent"**.

### 2.2 Select Claude Sonnet as the Model

- Click the model selector and choose **Claude Sonnet** (or your preferred model).
- Claude Sonnet is optimized for fast, accurate code generation and multi-file edits.

<!-- TODO: Add screenshot showing Agent mode with Claude Sonnet selected -->

### 2.3 Run the Implementation

Instruct Copilot to implement the plan by clicking "Start Implementation" or by explicitly saying "Now, implement the plan."

### 2.4 Watch Copilot Work

Copilot in Agent mode will:

1. **Create new agent files** — e.g., `backend/app/agents/look_and_find.py` and `backend/app/agents/character_glossary.py`
2. **Modify the workflow** — Add fan-out/fan-in edges in `workflow.py`
3. **Update data models** — Add new Pydantic models in `models.py` for activity page and glossary data
4. **Extend the API** — Ensure `StoryRequest` includes the new checkbox flags and `StoryResponse` includes the new page data
5. **Update the frontend form** — Add checkboxes to `StoryForm.jsx`
6. **Update the progress tracker** — Add new agent steps to `ProgressTracker.jsx`
7. **Add new page types** — Create rendering components for the activity and glossary pages in `StoryPage.jsx` or new components
8. **Update the storybook** — Modify `StoryBook.jsx` to include the new pages at the end

> **Tip:** Let Copilot make all the changes, then review them file-by-file. You can accept, reject, or modify individual changes.

### 2.5 Accept the Changes

Review each file change that Copilot proposes:
- Click through the diff view for each modified file
- Accept changes that look correct
- If any changes need adjustment, you can ask Copilot to revise specific parts

---

## Step 3: Review and Test

### 3.1 Restart the Application

After Copilot has made the changes:

```bash
# Restart the backend (if not using auto-reload)
# In the terminal running uvicorn, press Ctrl+C and restart:
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# The frontend (Vite) should auto-reload; if not, restart it:
cd frontend
npm run dev
```

### 3.2 Test All Scenarios

Test the following combinations to ensure the workflow handles all cases correctly:

| Test Case | Look & Find | Character Glossary | Expected Result |
|---|---|---|---|
| **Both enabled** | ✅ | ✅ | Story + Look & Find page + Character Glossary page at the end |
| **Only Look & Find** | ✅ | ❌ | Story + Look & Find page only |
| **Only Character Glossary** | ❌ | ✅ | Story + Character Glossary page only |
| **Neither enabled** | ❌ | ❌ | Original behavior — story only, no activity pages |

For each test:
1. Open **http://localhost:5173**
2. Toggle the checkboxes as indicated
3. Click **"Create My Story"**
4. Watch the **ProgressTracker** — verify the new agents appear (or don't appear) based on your selections
5. When generation completes, flip through the storybook and verify the activity pages render correctly at the end

### 3.3 Verify the Progress Tracker

- When Look & Find or Character Glossary agents are enabled, their steps should appear in the ProgressTracker
- When they're disabled, their steps should **not** appear — the tracker should look the same as the base application
- If both are enabled, they should show as running in parallel (both start before either completes, reflecting the fan-out pattern)

<!-- TODO: Add screenshot of ProgressTracker showing the new agents in parallel -->

### 3.4 Compare with the Reference Branch (Optional)

If you want to compare your Copilot-generated implementation against the reference:

```bash
# View the diff between your branch and the reference
git diff my-activity-pages..origin/activity-page-agents

# Or check out the reference branch to run it directly
git stash                             # Save your work
git checkout activity-page-agents     # Switch to reference
# Test the reference implementation...
git checkout my-activity-pages        # Switch back
git stash pop                         # Restore your work
```

---

## What to Look For

After the implementation is complete, review the code to understand these key architectural changes:

### Fan-Out / Fan-In Edges in `workflow.py`

The most important change is in the workflow definition. Look for:

```python
# Fan-out: Decision → [LookAndFindActivityAgent, CharacterGlossaryAgent]
builder.add_fan_out_edges(source="decision", targets=["look_and_find", "character_glossary"])

# Fan-in: [LookAndFindActivityAgent, CharacterGlossaryAgent] → FinalAssembler
builder.add_fan_in_edges(sources=["look_and_find", "character_glossary"], target="final_assembler")
```

> **Key concept:** Fan-out edges cause multiple executors to run in parallel from a single predecessor. Fan-in edges wait for all parallel branches to complete before proceeding. This is how the Agent Framework supports parallel agent execution.

### Executor Compatibility

When using `add_fan_out_edges()` and `add_fan_in_edges()`, the source and target executors must be compatible with each other. Pay attention to:

- **What the Decision executor outputs** when the story is approved — this must match what the new agents expect as input
- **What the new agents output** — this must be compatible with whatever fan-in target assembles the final result
- **Whether new intermediate executors are needed** to bridge incompatible types

### Conditional Workflow Paths

The implementation should conditionally include the fan-out/fan-in agents based on the user's checkbox selections. This might involve:

- Passing the checkbox states from the frontend through the API to the workflow
- Using conditional edges or runtime checks to skip disabled agents
- Handling the case where neither agent is enabled (direct output without fan-out)

### New Agent Structure

Each new agent should follow the same patterns as existing agents:

- **LookAndFindActivityAgent** — Examines the generated images (from shared state's `illustrated_draft`) and selects 3–5 items across various pages for the child to find
- **CharacterGlossaryAgent** — Reads the story outline/draft to extract characters and generate descriptions

### Frontend Changes

- **StoryForm** — Two new checkboxes with labels like "Generate Look & Find Activity Page" and "Generate Character Glossary"
- **ProgressTracker** — Conditionally shows the new agent steps based on whether they're enabled
- **StoryBook** — Activity pages appear after the "The End" page (or before it, depending on implementation)
- **StoryPage** — New rendering logic for the activity page and glossary page formats

---

## Reference Branch

The `activity-page-agents` branch contains a complete working implementation of this feature. It's intended as a **backup reference** — not something you should copy from directly.

```bash
# View the reference implementation
git checkout activity-page-agents

# Return to your working branch
git checkout my-activity-pages
```

> **Note:** There is also an `activity-page-agents-and-tts` branch that combines activity pages with TTS functionality. That represents the fully-extended application.

---

## Troubleshooting

### Copilot's plan doesn't seem to understand the Agent Framework APIs

Make sure the **Context7 MCP server** is enabled in your VS Code settings. You can also try adding `use context7` to the beginning of your prompt to explicitly trigger documentation fetching for the Agent Framework library.

### The workflow fails with executor compatibility errors

Fan-out/fan-in edges require compatible executor types. If you see errors about incompatible executors:
1. Check that the source executor's output type matches what the target executors expect
2. You may need to add an intermediate executor (adapter) that converts between types
3. Review the reference branch's `workflow.py` to see how compatibility is handled

### The new agents don't appear in the ProgressTracker

Ensure that:
1. The agent executor IDs used in the workflow match what the frontend expects
2. The ProgressTracker component has been updated with the new agent definitions
3. The SSE events for the new agents include the correct executor IDs

### Checkboxes don't affect the workflow

Verify that:
1. The checkbox state is included in the `StoryRequest` model (backend)
2. The frontend sends the checkbox values in the POST request body
3. The workflow conditionally adds/skips the fan-out edges based on these values

### One or both activity pages are empty

Check that:
1. The LookAndFindActivityAgent has access to the illustrated draft (images) via shared state
2. The CharacterGlossaryAgent has access to the story outline/draft
3. The prompts for each agent are detailed enough to produce quality output

---

## Next Steps

- [Guide: Adding Text-to-Speech](05-guide-tts.md) — Add Azure AI Speech narration to every story page
- The `activity-page-agents-and-tts` branch shows both features combined

[← Back to README](../README.md)
