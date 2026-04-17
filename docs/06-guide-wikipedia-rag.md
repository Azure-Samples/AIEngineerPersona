# Guide: Adding Wikipedia RAG

[← Back to README](../README.md) | [Prerequisites & Setup](01-prerequisites-and-setup.md) | [Architecture Overview](02-architecture-overview.md)

This step-by-step guide walks you through adding **Wikipedia-powered Retrieval-Augmented Generation (RAG)** to the Children's Story Studio, enabling users to create stories grounded in real-world facts from Wikipedia — using **GitHub Copilot** to plan and implement the changes.

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

By the end of this guide, the Story Form will include a new **Wikipedia Topic** section that allows the user to:

1. **Enter a real-world topic** (e.g., "Marie Curie", "Moon landing", "Photosynthesis") — the application fetches the corresponding Wikipedia article extract at generation time.

2. **Choose how Wikipedia content influences the story** via two modes:

   | Mode | Behavior |
   |---|---|
   | **Full Wikipedia Story** (`full`) | The AI creates the **entire story** — characters, setting, moral, and plot — derived from the Wikipedia article. The user's manual story fields (characters, setting, etc.) are ignored. |
   | **Wikipedia-Influenced Story** (`influence`) | The user's characters, setting, moral, and plot remain the primary drivers. Wikipedia facts are woven in as **background inspiration** and enrichment. |

3. **Graceful fallback** — If no Wikipedia article is found for the topic, the story is generated without Wikipedia content and the user is notified in the Progress Tracker.

### How It Works

The Wikipedia RAG feature operates at the **Orchestrator** level, enriching the prompt sent to the Story Architect agent:

```
User enters Wikipedia topic
         │
         ▼
┌─────────────────┐
│   Orchestrator  │
│                 │
│  1. Fetch Wikipedia article via opensearch API
│  2. Extract plain-text content (up to 10,000 chars)
│  3. Inject content into the Story Architect prompt
│     as "WIKIPEDIA CONTEXT (FULL MODE)" or
│     "WIKIPEDIA CONTEXT (INFLUENCE MODE)"
│                 │
└────────┬────────┘
         ▼
┌─────────────────┐
│ Story Architect │  ← Prompt now includes real-world facts
└─────────────────┘
```

### UI Changes

- A new **"Wikipedia Topic (optional)"** section appears at the top of the Story Form.
- Two **mode cards** (radio buttons) let the user select Full or Influence mode.
- When **Full mode** is selected, the Characters and World & Story sections are visually disabled with a notice explaining that the AI will derive everything from the article.
- The **Progress Tracker** displays new detail events: `wikipedia_fetched` (showing the resolved title, mode, and content length) and `wikipedia_not_found` (when no article matches the topic).

<!-- TODO: Add screenshot of the Story Form with Wikipedia topic section -->

---

## Why This Matters

This guide demonstrates several important patterns:

| Pattern | What It Shows |
|---|---|
| **Retrieval-Augmented Generation (RAG)** | Fetching external factual content at runtime and injecting it into LLM prompts to ground the output in real-world information |
| **External API Integration** | Calling the Wikipedia opensearch and query APIs asynchronously using `httpx` |
| **Prompt Enrichment** | Dynamically building prompts that combine user parameters with retrieved context, adapting format based on mode selection |
| **Dynamic UI Modes** | Conditionally enabling/disabling form sections based on user selection, providing clear visual feedback about which fields are active |
| **Graceful Degradation** | Handling missing articles or API failures without breaking the workflow |
| **Copilot-Driven Development** | How GitHub Copilot can implement a cross-cutting RAG feature that touches backend models, prompts, orchestrator logic, and frontend components |

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
   git checkout -b my-wikipedia-rag
   ```

> **Note:** This feature does not require any additional Azure resources or API keys. The Wikipedia API is free and public. The only new dependency is the `httpx` HTTP client library.

---

## Step 1: Plan the Implementation (Plan Mode + Claude Opus)

In this step, you'll use GitHub Copilot's **Plan mode** with **Claude Opus** (or your preferred model) to analyze the codebase and produce a detailed implementation plan — without making any code changes.

### 1.1 Open GitHub Copilot Chat

- Open the **Copilot Chat** panel in VS Code (click the Copilot icon in the sidebar, or press `Ctrl+Shift+I` / `Cmd+Shift+I`).

### 1.2 Switch to Plan Mode

- At the top of the Copilot Chat panel, switch the mode from **"Ask"** or **"Agent"** to **"Plan"**.

### 1.3 Select Claude Opus as the Model

- Click the model selector (usually shows the current model name) and choose **Claude Opus** (or your preferred model).
- Claude Opus excels at analyzing complex codebases and producing thorough, well-structured plans.

### 1.4 Paste the Sample Prompt

Copy and paste the following prompt into the Copilot Chat input:

> **Prompt:**
>
> Add a Wikipedia RAG (Retrieval-Augmented Generation) feature to the story generation workflow. This feature should allow users to optionally enter a real-world topic (e.g. "Marie Curie", "Moon landing", "Photosynthesis") and have the application fetch factual content from Wikipedia to ground the generated story in real-world information.
>
> There should be two modes for how the Wikipedia content is used:
>
> - **Full mode** — The AI creates the entire story (characters, setting, moral, plot) derived from the Wikipedia article. The user's manual story fields are ignored.
> - **Influence mode** — The user's characters, setting, moral, and plot remain the primary drivers, but Wikipedia facts are woven in as background inspiration. This should be the default.
>
> Key implementation details:
>
> - Use the public Wikipedia opensearch API to resolve the user's topic to the best-matching article, then fetch its plain-text extract. Use `httpx` for async HTTP requests. Truncate the extract to ~10,000 characters to stay within LLM context limits.
> - The Wikipedia content should be injected into the Orchestrator's prompt to the Story Architect — not into the agent itself. The prompt format should differ based on the selected mode.
> - Update the system prompt instructions so the Story Architect knows how to handle Wikipedia context in both modes. In both cases, the content should be simplified and adapted for children aged 5–8.
> - On the frontend, add a "Wikipedia Topic" section to the Story Form with a text input and two mode selection cards (Full vs. Influence). When Full mode is selected, visually disable the Characters and World & Story sections since the AI will derive everything from the article.
> - Update the Progress Tracker to show when Wikipedia content has been fetched (with the resolved title and content length) or when the topic wasn't found.
> - If no Wikipedia article is found, the story should still generate normally using the user's manual fields — don't break the workflow.

### 1.5 Review the Plan

Copilot (in Plan mode) will analyze the entire codebase and produce a detailed plan covering:

- **New files to create** — `backend/app/wikipedia.py` (Wikipedia fetch utility)
- **Existing files to modify** — `models.py` (new request fields), `prompts.py` (Wikipedia context instructions), `orchestrator.py` (RAG integration), `requirements.txt` (httpx dependency), `StoryForm.jsx` (topic input + mode cards), `StoryForm.module.css` (new styles), `ProgressTracker.jsx` (new event blocks)
- **Prompt engineering** — How to instruct the Story Architect to handle Full vs. Influence modes
- **UI behavior** — How the form dynamically adapts when Full mode is selected

**Take time to review the plan carefully.** Ask follow-up questions if anything is unclear:

- *"How will the orchestrator handle the case where the Wikipedia fetch fails?"*
- *"What happens in Full mode if the Wikipedia extract is very short?"*
- *"How should the form validation work when Full mode is selected — are the character and setting fields still required?"*

> **Experiment:** Try refining the prompt or asking Copilot to reconsider specific aspects of the plan. For example:
> - *"What if we also added a preview of the Wikipedia article summary in the form?"*
> - *"Should there be a character count indicator for the fetched Wikipedia content?"*

---

## Step 2: Implement with GitHub Copilot (Agent Mode + Claude Sonnet)

Once you're satisfied with the plan, switch to **Agent mode** to let Copilot implement the changes.

### 2.1 Switch to Agent Mode

- Change the mode at the top of the Copilot Chat panel from **"Plan"** to **"Agent"**.

### 2.2 Select Claude Sonnet as the Model

- Click the model selector and choose **Claude Sonnet** (or your preferred model).
- Claude Sonnet is optimized for fast, accurate code generation and multi-file edits.

### 2.3 Run the Implementation

Instruct Copilot to implement the plan by clicking "Start Implementation" or by explicitly saying "Now, implement the plan."

### 2.4 Watch Copilot Work

Copilot in Agent mode will make changes across multiple files:

1. **Backend — New Wikipedia utility:**
   - Create `backend/app/wikipedia.py`
   - Implement async Wikipedia opensearch resolution and extract fetching using `httpx`
   - Return a `WikipediaResult` dataclass with title, extract, and URL
   - Handle errors and missing articles gracefully

2. **Backend — Model updates:**
   - Add `wikipedia_topic` (optional string) and `wikipedia_mode` (literal `"full"` | `"influence"`) to `StoryRequest` in `models.py`

3. **Backend — Prompt updates:**
   - Add Wikipedia context handling instructions to the Story Architect system prompt in `prompts.py`
   - Cover both Full mode (derive everything from Wikipedia) and Influence mode (blend with user parameters)

4. **Backend — Orchestrator integration:**
   - Modify `orchestrator.py` to call `fetch_wikipedia()` when a topic is provided
   - Emit `wikipedia_fetched` or `wikipedia_not_found` progress events
   - Build the Story Architect prompt conditionally based on the Wikipedia mode
   - In Full mode, skip user's manual story fields; in Influence mode, append Wikipedia context

5. **Backend — Dependencies:**
   - Add `httpx>=0.27.0` to `requirements.txt`

6. **Frontend — Story Form:**
   - Add Wikipedia topic input and mode selection cards to `StoryForm.jsx`
   - Implement dynamic disabling of Characters and World & Story sections in Full mode
   - Add corresponding styles in `StoryForm.module.css`

7. **Frontend — Progress Tracker:**
   - Add `WikipediaFetchedBlock` and `WikipediaNotFoundBlock` components to `ProgressTracker.jsx`
   - Include new event types in active step status resolution

> **Tip:** Let Copilot make all the changes, then review them file-by-file before accepting.

### 2.5 Accept the Changes

Review each file change:
- Verify the Wikipedia fetch utility properly handles error cases and returns `None` on failure
- Check that the `StoryRequest` model includes sensible defaults (`wikipedia_mode` defaults to `"influence"`)
- Ensure the orchestrator correctly builds different prompts for Full vs. Influence modes
- Confirm the frontend only sends `wikipedia_topic` and `wikipedia_mode` when a topic is provided
- Verify the form correctly disables sections in Full mode

---

## Step 3: Review and Test

### 3.1 Install New Dependencies

The Wikipedia RAG feature requires the `httpx` HTTP client library:

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt
```

### 3.2 Restart the Application

```bash
# Restart the backend
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# The frontend should auto-reload; if not:
cd frontend
npm run dev
```

### 3.3 Test Influence Mode

1. **Enter a Wikipedia topic** — Type "Marie Curie" in the Wikipedia Topic field.
2. **Select "Wikipedia-Influenced Story"** (this is the default mode).
3. **Fill in the story fields as usual** — main character, setting, moral, etc.
4. **Generate the story.**
5. **Check the Progress Tracker** — You should see a "Wikipedia content retrieved" event showing:
   - Resolved title (e.g., "Marie Curie")
   - Mode: "Influence — blended with your story details"
   - Content length (e.g., "8,432 characters fetched")
6. **Read the generated story** — Real-world facts about Marie Curie should be woven into the narrative alongside your custom characters and setting.

### 3.4 Test Full Mode

1. **Enter a Wikipedia topic** — Type "Moon landing" in the Wikipedia Topic field.
2. **Select "Full Wikipedia Story"** mode.
3. **Notice the form** — The Characters and World & Story sections should appear disabled with a notice: *"Not used in Full Wikipedia Story mode — the AI will create characters from the article."*
4. **Generate the story.**
5. **Read the generated story** — Characters, setting, moral, and plot should all be derived from the Moon landing Wikipedia article, retold as a children's story.

### 3.5 Test Without Wikipedia

1. **Leave the Wikipedia Topic field empty.**
2. **Generate a story as usual** with your own characters, setting, etc.
3. **Verify** the story generates normally without any Wikipedia influence — the feature is fully optional.

### 3.6 Test Error Handling

1. **Enter a nonsensical topic** — Type something like "xyzzy12345nosuchpage" in the Wikipedia Topic field.
2. **Generate the story.**
3. **Check the Progress Tracker** — You should see a "Wikipedia topic not found" notice.
4. **Verify** the story generates normally using the user's manual story fields as a fallback.

### 3.7 Compare with the Reference Branch (Optional)

```bash
# View diff against reference
git diff my-wikipedia-rag..origin/wikipedia-rag

# Or check out the reference to test it
git stash
git checkout wikipedia-rag
# Test...
git checkout my-wikipedia-rag
git stash pop
```

---

## What to Look For

After the implementation is complete, review the code to understand these key patterns:

### Wikipedia Article Resolution

The fetch utility uses a two-step process to go from a user's free-text topic to a clean article extract:

```python
# Step 1: opensearch — resolve "Marie Curie" → "Marie Curie" (canonical title)
params = {"action": "opensearch", "search": topic, "limit": 1, "format": "json"}

# Step 2: query extracts — fetch the full plain-text content
params = {"action": "query", "prop": "extracts", "explaintext": 1, "titles": resolved_title, "format": "json"}
```

**Key points:**
- The opensearch API handles fuzzy matching — "moon landing" resolves to the correct Wikipedia article even if the exact title differs.
- The extract is plain text (no HTML/wikitext) thanks to `explaintext=1`.
- Content is truncated to 10,000 characters to avoid exceeding LLM context limits.

### Prompt Construction by Mode

The orchestrator builds fundamentally different prompts depending on the mode:

**Full mode** — User story fields are ignored; the prompt instructs the Story Architect to derive everything from Wikipedia:
```python
prompt_parts = [
    "Create a children's story outline based entirely on the Wikipedia",
    "content provided below. Invent appropriate characters (with vivid",
    "visual descriptions), a setting, a moral lesson, and a plot that",
    "faithfully retells the real-world information for young readers.",
]
```

**Influence mode** — User story fields come first, then Wikipedia context is appended:
```python
prompt_parts = [
    "Create a story outline based on these parameters:",
    f"- Main character: {request.main_character}",
    # ... other user parameters ...
]
prompt_parts += wikipedia_context_parts  # Appended after user parameters
```

### Dynamic Form Behavior

The frontend adapts the form based on the combination of topic presence and mode selection:

- **No topic** → Mode cards are visually disabled; all story fields are active and required.
- **Topic + Influence mode** → Mode cards are active; all story fields remain active and required.
- **Topic + Full mode** → Mode cards are active; Characters and World & Story sections are disabled with explanatory notices.

This is implemented using a `<fieldset disabled={isFullMode}>` wrapper, which natively disables all child inputs.

### Progress Event Streaming

Two new SSE event types provide real-time feedback:

- `wikipedia_fetched` — Emitted when the Wikipedia article is successfully retrieved. Includes the resolved title, URL, extract length, and mode.
- `wikipedia_not_found` — Emitted when no Wikipedia article matches the user's topic. The story generation continues without Wikipedia content.

---

## Reference Branch

The `wikipedia-rag` branch contains a complete working implementation of this feature.

```bash
# View the reference implementation
git checkout wikipedia-rag

# Return to your working branch
git checkout my-wikipedia-rag
```

---

## Troubleshooting

### Wikipedia topic returns "not found" for a valid topic

1. **Check spelling** — The Wikipedia opensearch API is forgiving but may not resolve very unusual spellings.
2. **Try the canonical name** — Use the exact Wikipedia article title (e.g., "Marie Curie" instead of "madame curie scientist").
3. **Check network connectivity** — The backend needs outbound HTTPS access to `en.wikipedia.org`.

### Story doesn't seem influenced by Wikipedia content

1. **Check the Progress Tracker** — Verify a `wikipedia_fetched` event appears with a non-zero content length.
2. **Check the mode** — In Influence mode, the Wikipedia content is blended with user parameters. The influence may be subtle. Try Full mode for a more obvious effect.
3. **Try a more specific topic** — Broad topics may produce very general content. Specific topics (e.g., "Apollo 11" instead of "space") produce more distinctive story elements.

### Form fields are disabled when they shouldn't be

1. **Check the Wikipedia mode** — Fields are only disabled in Full mode when a topic is entered.
2. **Clear the Wikipedia Topic field** — Removing the topic text should re-enable all fields regardless of mode.
3. **Restart the Vite dev server** if CSS changes aren't reflected.

### `ModuleNotFoundError: No module named 'httpx'`

Install the httpx dependency:
```bash
cd backend
source .venv/bin/activate
pip install httpx
```

Or reinstall all dependencies:
```bash
pip install -r requirements.txt
```

### Wikipedia fetch times out or errors

The Wikipedia API requests have a 10-second timeout. If you're behind a corporate proxy or firewall:
1. Check that `https://en.wikipedia.org` is accessible from your machine.
2. If needed, configure proxy settings for `httpx` in the `wikipedia.py` utility.

### Copilot produces a different implementation structure

The prompt provides detailed guidance, but Copilot may organize code slightly differently. Key things to verify:
- The Wikipedia fetch is **async** (uses `httpx.AsyncClient`, not `requests`)
- The prompt injection happens in the **orchestrator**, not in the agent itself
- The `StoryRequest` model includes both `wikipedia_topic` and `wikipedia_mode` fields
- The frontend only sends Wikipedia fields when a topic is actually provided

---

## Next Steps

- Try the [Activity Page Agents guide](04-guide-activity-page-agents.md) to add Look & Find and Character Glossary pages.
- Try the [Text-to-Speech guide](05-guide-tts.md) to add narration to every story page.
- Add [OpenTelemetry observability](07.a-guide-otel-observability-ai-toolkit.md) to trace the full agent workflow including Wikipedia fetch timing.
- Experiment further: try different topics, compare Full vs. Influence mode outputs, or add a Wikipedia article preview to the form.

[← Back to README](../README.md)
