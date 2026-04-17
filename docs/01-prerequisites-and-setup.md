# Prerequisites & Environment Setup

[← Back to README](../README.md)

This document covers everything you need to install, configure, and provision before running Children's Story Studio or following the extension guides.

---

## Table of Contents

- [Required Tools](#required-tools)
- [VS Code Extensions](#vs-code-extensions)
- [Azure Resource Provisioning](#azure-resource-provisioning)
  - [Azure AI Foundry Project](#azure-ai-foundry-project)
  - [Azure AI Speech Resource (TTS Guide Only)](#azure-ai-speech-resource-tts-guide-only)
- [Environment Configuration](#environment-configuration)
- [Local Setup](#local-setup)
  - [Backend](#backend)
  - [Frontend](#frontend)
- [Authentication](#authentication)
- [VS Code Tasks](#vs-code-tasks)

---

## Required Tools

Ensure the following tools are installed on your machine:

| Tool | Minimum Version | Purpose |
|---|---|---|
| **Python** | 3.11+ | Backend runtime |
| **Node.js** | 18+ | Frontend runtime (includes `npm`) |
| **VS Code** | Latest | Development environment |
| **Azure CLI** | Latest | Authentication (`az login`) and resource management |
| **Git** | Latest | Version control, branch switching |

> **Verify installations:**
> ```bash
> python --version    # Should show 3.11+
> node --version      # Should show 18+
> code --version      # Should print VS Code version
> az --version        # Should print Azure CLI version
> git --version       # Should print Git version
> ```

---

## VS Code Extensions

The following VS Code extensions are **required** for the guided walkthroughs. Make sure each is installed and enabled before proceeding.

### GitHub Copilot & GitHub Copilot Chat

The extension guides rely heavily on GitHub Copilot for code generation. You'll use two distinct modes:

- **Plan Mode (with Claude Opus, or your preferred model)** — Copilot analyzes your codebase and produces a detailed implementation plan without making changes. Use this first to understand the scope of work.
- **Agent Mode (with Claude Sonnet, or your preferred model)** — Copilot actively implements changes across multiple files. Use this after reviewing and approving the plan.

> **Install:** Search for "GitHub Copilot" in the VS Code Extensions panel (`Ctrl+Shift+X` / `Cmd+Shift+X`) and install both **GitHub Copilot** and **GitHub Copilot Chat**.

### VS Code AI Toolkit

The **AI Toolkit for VS Code** (published by Microsoft) provides AI-focused development capabilities that you'll use throughout these guides:

- **Agent Trace Viewer** — View OpenTelemetry traces from your agent workflow directly in VS Code, including LLM call details, prompt/response inspection, and per-agent latency. Used in the [OTEL Observability guide (AI Toolkit variant)](07.a-guide-otel-observability-ai-toolkit.md).
- **Model Catalog** — Browse and compare available AI models from Azure AI Foundry without leaving your editor.
- **Prompt Playground** — Test and iterate on system prompts before committing them into agent code — useful when designing new agents in the [Activity Page Agents guide](04-guide-activity-page-agents.md).

> **Install:** Search for "AI Toolkit" in the VS Code Extensions panel and install **AI Toolkit for Visual Studio Code** (published by Microsoft).

<!-- TODO: Add screenshot of AI Toolkit extension in the extensions panel -->

### Context7 MCP Server

**Context7** is a Model Context Protocol (MCP) server that provides GitHub Copilot with up-to-date, version-specific documentation for libraries and frameworks. This is particularly valuable when working with newer libraries like Microsoft Agent Framework, where Copilot's training data may not include the latest APIs.

When Context7 is enabled and you include `use context7` in your Copilot prompts, it will automatically fetch current documentation for the libraries you're using — ensuring generated code uses correct, up-to-date APIs.

> **Setup:** Follow the [Context7 MCP Server setup instructions](https://github.com/upstash/context7) to add it to your VS Code MCP configuration. Ensure the Context7 MCP server is listed and enabled in your VS Code MCP settings.

<!-- TODO: Add screenshot of Context7 in VS Code MCP settings -->

---

## Azure Resource Provisioning

### Azure AI Foundry Project

The base application requires an **Azure AI Foundry** project with two model deployments. Follow these steps to provision the required resources.

#### Step 1: Create an Azure AI Foundry Hub and Project

1. Navigate to the [Azure Portal](https://portal.azure.com) and search for **"Azure AI Foundry"**.
2. Click **+ Create** to create a new hub resource (or use an existing one).
3. Select your **Subscription**, **Resource Group**, and **Region**.
4. Once the hub is created, navigate into it and click **+ New project** to create a project within the hub.
5. Give your project a name (e.g., `childrens-story-studio`) and click **Create**.

<!-- TODO: Add screenshot of Azure AI Foundry project creation -->

#### Step 2: Deploy the Chat Model (`gpt-5.2`)

1. Inside your Azure AI Foundry project, navigate to **Deployments** (or **Model catalog**).
2. Search for and select **GPT-5.2** (or your preferred model).
3. Click **Deploy** and configure the deployment:
   - **Deployment name:** `gpt-5.2` (or your preferred name — you'll set this in `.env`)
   - **Model version:** Use the latest available version
   - **Deployment type:** Standard
4. Note the deployment name for your `.env` configuration.

#### Step 3: Deploy the Image Generation Model

1. In the same Deployments section, search for an image generation model (e.g., **gpt-image-1**, **gpt-image-1.5** or **dall-e-3**).
2. Click **Deploy** and configure:
   - **Deployment name:** `gpt-image-1.5` (or your preferred name — match whatever you set in `.env`)
   - Use default settings for other options.
3. Note the deployment name.

<!-- TODO: Add screenshot of model deployments list -->

#### Step 4: Get the Project Endpoint

1. In your Azure AI Foundry project, navigate to **Overview** or **Settings**.
2. Copy the **Project endpoint URL** — it will look like:
   ```
   https://<your-resource>.services.ai.azure.com/api/projects/<your-project>
   ```
3. This is the value for `FOUNDRY_PROJECT_ENDPOINT` in your `.env`.

#### Step 5: Configure Role-Based Access

Ensure your Azure account has the necessary role assignments on the AI Foundry resource:

- **Cognitive Services OpenAI User** (or **Cognitive Services Contributor**) — required for chat and image generation API access.

You can assign roles via the Azure Portal under **Access control (IAM)** on the AI Foundry resource, or via CLI:

```bash
# Get your Azure account object ID
az ad signed-in-user show --query id -o tsv

# Assign the role (replace placeholders)
az role assignment create \
  --role "Cognitive Services OpenAI User" \
  --assignee <your-object-id> \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<resource-name>
```

---

### Azure AI Speech Resource (TTS Guide Only)

> **Note:** This section is only required if you plan to follow the [Text-to-Speech Guide](05-guide-tts.md). Skip this for the base application and the Activity Page Agents guide.

#### Step 1: Create an Azure AI Speech Resource

1. In the [Azure Portal](https://portal.azure.com), search for **"Speech"** and select **Speech** under Azure AI services.
2. Click **+ Create**.
3. Configure:
   - **Subscription:** Your Azure subscription
   - **Resource Group:** Same as your AI Foundry resources (recommended)
   - **Region:** Choose a region that supports neural TTS voices (e.g., `eastus`, `westus2`, `westeurope`). Note this region — you'll need it for `AZURE_SPEECH_REGION`.
   - **Name:** e.g., `story-studio-speech`
   - **Pricing tier:** Standard S0
4. Click **Review + Create**, then **Create**.

<!-- TODO: Add screenshot of Speech resource creation -->

#### Step 2: Gather Speech Resource Details

After the resource is created, you'll need three values for your `.env`:

1. **Region** (`AZURE_SPEECH_REGION`): The region you selected (e.g., `eastus`).
2. **Endpoint** (`AZURE_SPEECH_ENDPOINT`): Found in the resource's **Overview** or **Keys and Endpoint** section. It will look like:
   ```
   https://<region>.api.cognitive.microsoft.com/
   ```
3. **Resource ID** (`AZURE_SPEECH_RESOURCE_ID`): Found in the resource's **Properties** section. It will look like:
   ```
   /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<resource-name>
   ```

#### Step 3: Configure Role-Based Access for Speech

Assign the **Cognitive Services Speech User** role to your Azure account on the Speech resource:

```bash
az role assignment create \
  --role "Cognitive Services Speech User" \
  --assignee <your-object-id> \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<speech-resource-name>
```

> **Important:** The TTS implementation uses `DefaultAzureCredential` (via `az login`) for authentication — not API keys. The role assignment above is what grants access.

---

## Environment Configuration

The backend uses a `.env` file for configuration. A `.env.example` template is provided.

### Step 1: Create Your `.env` File

```bash
cd backend
cp .env.example .env
```

### Step 2: Fill In the Values

Open `backend/.env` in your editor and configure the following variables:

#### Base Application Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `FOUNDRY_PROJECT_ENDPOINT` | **Yes** | `""` | Your Azure AI Foundry project endpoint URL |
| `FOUNDRY_MODEL_DEPLOYMENT_NAME` | No | `gpt-5.2` | The name of your chat model deployment |
| `FOUNDRY_IMAGE_MODEL_DEPLOYMENT_NAME` | No | `gpt-image-1.5` | The name of your image generation model deployment |
| `SKIP_STORY_REVIEWER` | No | `false` | Set to `true` to bypass the StoryReviewer agent (faster generation, useful for demos) |
| `CORS_ORIGIN` | No | `http://localhost:5173` | The frontend's origin URL for CORS |

#### TTS Variables (Only for [TTS Guide](05-guide-tts.md))

| Variable | Required for TTS | Default | Description |
|---|---|---|---|
| `AZURE_SPEECH_REGION` | **Yes** | — | Azure region of your Speech resource (e.g., `eastus`) |
| `AZURE_SPEECH_ENDPOINT` | **Yes** | — | Full endpoint URL of your Speech resource |
| `AZURE_SPEECH_RESOURCE_ID` | **Yes** | — | Full Azure resource ID of your Speech resource |

### Example `.env` File

```env
# Azure AI Foundry
FOUNDRY_PROJECT_ENDPOINT=https://your-resource.services.ai.azure.com/api/projects/your-project
FOUNDRY_MODEL_DEPLOYMENT_NAME=gpt-5.2
FOUNDRY_IMAGE_MODEL_DEPLOYMENT_NAME=gpt-image-1.5

# Application settings
SKIP_STORY_REVIEWER=false
CORS_ORIGIN=http://localhost:5173

# Azure AI Speech (only needed for TTS functionality)
# AZURE_SPEECH_REGION=eastus
# AZURE_SPEECH_ENDPOINT=https://eastus.api.cognitive.microsoft.com/
# AZURE_SPEECH_RESOURCE_ID=/subscriptions/.../resourceGroups/.../providers/Microsoft.CognitiveServices/accounts/...
```

---

## Local Setup

### Backend

```bash
# Navigate to the backend directory
cd backend

# Create a Python virtual environment
python -m venv .venv

# Activate the virtual environment
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows

# Install Python dependencies
pip install -r requirements.txt
```

> **Tip:** If you encounter issues installing `agent-framework-core` or `agent-framework-azure-ai`, ensure your `pip` is up to date: `pip install --upgrade pip`

### Frontend

```bash
# Navigate to the frontend directory
cd frontend

# Install npm dependencies
npm install
```

---

## Authentication

This application uses **`DefaultAzureCredential`** from the Azure Identity library for all Azure service authentication. This means:

1. **No API keys are stored in configuration** — authentication is handled through your Azure identity.
2. **You must be logged in via Azure CLI** before starting the backend:
   ```bash
   az login
   ```
3. **Your Azure account must have the appropriate role assignments** on the Azure resources (see the provisioning sections above).

`DefaultAzureCredential` tries multiple authentication methods in order (environment variables, managed identity, Azure CLI, etc.). For local development, it will use your `az login` session.

> **Before every demo or development session**, verify your login is current:
> ```bash
> az account show    # Should display your active subscription
> ```
> If your token has expired, run `az login` again.

---

## VS Code Tasks

This repository includes pre-configured VS Code tasks in `.vscode/tasks.json` that simplify setup and startup:

| Task | What It Does |
|---|---|
| **Backend: Install Python deps** | Creates a virtual environment and installs `requirements.txt` |
| **Backend: Start (uvicorn)** | Activates the venv and starts the FastAPI server on port 8000 with auto-reload |
| **Frontend: Install npm deps** | Runs `npm install` in the frontend directory |
| **Frontend: Start (Vite dev)** | Starts the Vite development server |

To run a task: `Ctrl+Shift+P` (or `Cmd+Shift+P` on macOS) → **"Tasks: Run Task"** → select the task.

> **Tip:** Use the **"Full Stack"** compound launch configuration (press `F5`) to start both the backend and frontend simultaneously.

---

## Next Steps

- [Architecture Overview](02-architecture-overview.md) — Understand the system design and agent workflow
- [Running the Demo](03-running-the-demo.md) — Start the application and run through a demo
- [Guide: Activity Page Agents](04-guide-activity-page-agents.md) — Extend the workflow with new agents
- [Guide: Text-to-Speech](05-guide-tts.md) — Add narration capabilities

[← Back to README](../README.md)
