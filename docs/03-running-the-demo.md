# Running the Demo

[← Back to README](../README.md) | [Prerequisites & Setup](01-prerequisites-and-setup.md) | [Architecture Overview](02-architecture-overview.md)

This guide walks you through running Children's Story Studio and provides talking points for demonstrating it to customers.

---

## Table of Contents

- [Before You Start](#before-you-start)
- [Starting the Application](#starting-the-application)
  - [Option A: VS Code Tasks (Recommended)](#option-a-vs-code-tasks-recommended)
  - [Option B: Manual Terminal Commands](#option-b-manual-terminal-commands)
- [Walking Through the Demo](#walking-through-the-demo)
  - [Step 1: The Story Form](#step-1-the-story-form)
  - [Step 2: Real-Time Progress Tracking](#step-2-real-time-progress-tracking)
  - [Step 3: The Generated Storybook](#step-3-the-generated-storybook)
- [Demo Talking Points](#demo-talking-points)
- [Tips for a Smooth Demo](#tips-for-a-smooth-demo)
- [Feature Flags for Demos](#feature-flags-for-demos)

---

## Before You Start

Ensure you have completed all steps in [Prerequisites & Setup](01-prerequisites-and-setup.md):

- [ ] Python 3.11+ and Node.js 18+ installed
- [ ] Backend virtual environment created and dependencies installed
- [ ] Frontend npm dependencies installed
- [ ] `backend/.env` configured with your Azure AI Foundry values
- [ ] Azure CLI logged in (`az login`) — verify with `az account show`

> **Pro tip:** Run `az account get-access-token --query expiresOn -o tsv` to check when your token expires. If it's within the next hour, run `az login` again before starting.

---

## Starting the Application

### Option A: VS Code Tasks (Recommended)

1. Open the project in VS Code.
2. Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on macOS) and type **"Tasks: Run Task"**.
3. Run **"Backend: Start (uvicorn)"** — this starts the FastAPI server on port 8000.
4. Run **"Frontend: Start (Vite dev)"** — this starts the Vite dev server on port 5173.

Alternatively, press **F5** to use the **"Full Stack"** compound launch configuration, which starts both simultaneously.

### Option B: Manual Terminal Commands

**Terminal 1 — Backend:**
```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
```

Once both are running, open **http://localhost:5173** in your browser.

---

## Walking Through the Demo

### Step 1: The Story Form

<!-- TODO: Add screenshot of the StoryForm with pre-populated values -->

When the application loads, you'll see the **Story Form** with fields for defining your children's story:

| Field | Description | Default Value |
|---|---|---|
| **Main Character** | The protagonist of the story | Pre-populated with an example character |
| **Supporting Characters** | Additional characters (add/remove dynamically) | Pre-populated with example characters |
| **Setting** | Where the story takes place | Pre-populated with a whimsical setting |
| **Moral** | The lesson or moral of the story | Pre-populated with an example moral |
| **Main Problem** | The central conflict to be resolved | Pre-populated with an example problem |
| **Additional Details** | Any extra instructions or preferences | Optional |

> **For demos:** The default values are designed to produce an engaging story right out of the box. You can click **"Create My Story"** immediately without changing anything for a quick demo, or customize the fields to show the flexibility of the system.

### Step 2: Real-Time Progress Tracking

<!-- TODO: Add screenshot of the ProgressTracker in full-page mode during generation -->

After submitting the form, the application transitions to a **full-page progress tracker** that displays the real-time status of each agent in the workflow:

1. **Orchestrator** — Creating the story structure and outline
2. **Story Architect** — Writing the narrative text for each page
3. **Art Director** — Generating illustrations (you'll see image thumbnails appear in real-time)
4. **Story Reviewer** — Evaluating story quality (or auto-approved if reviewer is skipped)
5. **Decision** — Final approval or revision loop

Each step shows:
- **Status indicator** — Pending (gray), In Progress (animated), Completed (green)
- **Expandable detail panel** — Click to see the actual prompts sent to the LLM, responses received, page-by-page content, and generated images

> **Talking point:** Highlight how the real-time streaming lets you observe each agent's work as it happens — this is powered by Server-Sent Events (SSE) from the Agent Framework's event system.

If a revision is triggered:
- You'll see a revision notification appear
- The workflow loops back to the Orchestrator with the reviewer's feedback
- The progress tracker groups events by revision round so you can see the difference between rounds

### Step 3: The Generated Storybook

<!-- TODO: Add screenshot of the StoryBook view with the cover page displayed -->

Once generation completes, the view transitions to an **interactive storybook**:

- **Cover Page** — Features the story title overlaid on a generated cover illustration, with a moral tagline
- **Story Pages** (6–8 pages) — Each page shows an illustration on top and narrative text below, with character tags
- **"The End" Page** — A decorative closing illustration

**Navigation:**
- Use the **Previous / Next** buttons to flip through pages
- Click the **dot indicators** at the bottom to jump to any page
- A collapsible **sidebar** on the left shows the progress tracker from the generation phase, so you can review what each agent did

> **Talking point:** The storybook UI is entirely generated — every page's text, illustrations, and even the cover art were created by the coordinated agent workflow.

---

## Demo Talking Points

Use these talking points when presenting to customers:

### Multi-Agent Orchestration
> "This application demonstrates how Microsoft Agent Framework enables you to decompose a complex creative task into specialized agents — each with a distinct role — and orchestrate them into a coordinated workflow. The Orchestrator plans the story, the Architect writes it, the Art Director illustrates it, and the Reviewer quality-checks it."

### Workflow-as-Code
> "The entire agent workflow is defined in Python code using the Agent Framework's `WorkflowBuilder`. Adding new agents, changing the execution order, or introducing parallel branches is a code change — not a configuration or no-code tool. This gives engineering teams full control and testability."

### Real-Time Streaming
> "Every step of the workflow streams progress to the browser via Server-Sent Events. This isn't polling — it's a push-based stream that lets the UI react instantly as each agent starts, processes, and completes its work. You can even see the image prompts and LLM responses in real-time."

### Conditional Workflow Paths
> "The workflow supports conditional branching. For example, we can skip the Story Reviewer agent entirely with a feature flag — useful for faster demos or when you want to show different workflow configurations. This same pattern can be used for any conditional business logic."

### Revision Loop (Quality Gate)
> "The Decision agent acts as a quality gate. If the Reviewer identifies issues, the Decision agent sends a `RevisionSignal` back to the Orchestrator with specific feedback, and the entire pipeline re-executes with that context. This 'human-in-the-loop without the human' pattern shows how agents can self-correct."

### Concurrent Image Generation
> "The Art Director generates all illustrations concurrently using a semaphore-controlled pool of 5 parallel requests. This is a practical pattern for real-world applications where you need to make many API calls efficiently."

### Extensibility
> "This is a starting point, not an end state. The extension guides show how you can add entirely new agents (like a Look & Find activity page generator) or new AI modalities (like text-to-speech narration) by building on this same workflow."

---

## Tips for a Smooth Demo

1. **Pre-run once before the demo** — The first run warms up connections and ensures your Azure credentials are active. Generate one story beforehand and verify it completes successfully.

2. **Check your `az login` session** — Azure CLI tokens expire. Run `az account show` before the demo to confirm you're still authenticated.

3. **Use the default form values** — They're carefully chosen to produce a good story. Modifying them is great for showing flexibility, but stick with defaults for your first run.

4. **Expand the detail panels** — During generation, click on the agent steps in the progress tracker to show the actual LLM prompts and responses. This is often the most impressive part for technical audiences.

5. **Have the code open** — For technical audiences, keep `workflow.py` open in a VS Code tab so you can show how the agent graph is defined. The code is clean and self-explanatory.

6. **Consider using `SKIP_STORY_REVIEWER=true`** — This cuts generation time significantly by skipping the review and potential revision loops. Set this in your `.env` for time-constrained demos (see [Feature Flags](#feature-flags-for-demos) below).

7. **Use a reliable network** — The application makes multiple calls to Azure AI services. A stable connection ensures a smooth experience.

8. **Budget 3–5 minutes for generation** — A full story with 6–8 illustrated pages plus cover and "The End" takes a few minutes. Use this time to discuss the architecture with the audience.

---

## Feature Flags for Demos

| Environment Variable | Value | Effect |
|---|---|---|
| `SKIP_STORY_REVIEWER` | `true` | Bypasses the StoryReviewer agent — story goes directly from ArtDirector to Decision (auto-approved). Faster but no quality review. |
| `SKIP_STORY_REVIEWER` | `false` (default) | Full pipeline with review and potential revision loops. More impressive for showcasing the complete workflow. |

Edit `backend/.env` and restart the backend to change this setting.

---

## What's Next?

Now that you've seen the base application in action, follow the extension guides to add new capabilities:

1. [Guide: Adding Activity Page Agents](04-guide-activity-page-agents.md) — Add Look & Find and Character Glossary agents to the workflow
2. [Guide: Adding Text-to-Speech](05-guide-tts.md) — Add Azure AI Speech narration to every story page

Both guides walk you through using GitHub Copilot to implement the changes — demonstrating how an AI engineer would extend an existing agent-based application.

[← Back to README](../README.md)
