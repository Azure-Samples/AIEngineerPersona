# Local Quickstart

[← Back to README](../README.md)

The fastest path to running Children's Story Studio locally. For more detail on any step (Azure AI Foundry provisioning, RBAC, VS Code extensions, etc.), see [Prerequisites & Environment Setup](01-prerequisites-and-setup.md).

---

## What you need

- **Python 3.11+**, **Node.js 18+**, **Azure CLI**, **Git**
- An **Azure AI Foundry** project with two model deployments:
  - a chat model (e.g. `gpt-5.2` / `gpt-5.4` / `gpt-4o`)
  - an image model (e.g. `gpt-image-1.5` / `gpt-image-1` / `dall-e-3`)
- Your Azure account assigned **`Cognitive Services OpenAI User`** (or `Azure AI User`) on that Foundry resource — the app authenticates with `DefaultAzureCredential`, no API keys.

> Don't have a Foundry project yet? Follow the [Azure Resource Provisioning section of the prereqs doc](01-prerequisites-and-setup.md#azure-resource-provisioning), then come back.

---

## 1. Sign in to Azure

```bash
az login
```

`DefaultAzureCredential` picks up this session — no further auth config needed.

---

## 2. Configure the backend

```bash
cd backend
cp .env.example .env
```

Open `backend/.env` and set, at minimum:

```env
FOUNDRY_PROJECT_ENDPOINT=https://<your-foundry-account>.services.ai.azure.com/api/projects/<your-project>
FOUNDRY_MODEL_DEPLOYMENT_NAME=gpt-5.4
FOUNDRY_IMAGE_MODEL_DEPLOYMENT_NAME=gpt-image-1.5
```

The TTS / OpenTelemetry variables in `.env.example` are only needed for the optional features added by the [Guides](../README.md#guides) — leave them at the placeholder values for the core app.

---

## 3. Start the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate            # macOS / Linux
# .venv\Scripts\activate              # Windows PowerShell
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

You should see `Uvicorn running on http://0.0.0.0:8000` and `Application startup complete.` Keep this terminal running.

---

## 4. Start the frontend

In a **second** terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (typically `http://localhost:5173`) and generate a story.

---

## VS Code shortcut

The repo ships a `Full Stack` compound launch config — press **F5** in VS Code to start both the backend and the Vite dev server in one shot. (See `.vscode/launch.json` and `.vscode/tasks.json`.)

---

## Troubleshooting one-liners

| Symptom | Fix |
| --- | --- |
| `DefaultAzureCredential failed to retrieve a token` | `az login` again, then confirm `az account show` returns the right subscription. |
| `403 Forbidden` from Foundry | Your account is missing the `Cognitive Services OpenAI User` (or `Azure AI User`) role on the Foundry resource. |
| `404` on `/api/generate-story` | The frontend is hitting Vite's proxy; ensure the backend is running on port `8000`. |
| `Pydantic Invalid JSON: EOF while parsing a string` | gpt-5.x reasoning models eating the response budget. The `all-features` branch has a fix; on `main` you may need to lower the model's reasoning effort or switch to `gpt-4o`. |

---

## Next steps

- [Architecture Overview](02-architecture-overview.md) — How the five agents are wired together.
- [Running the Demo](03-running-the-demo.md) — Demo-flow narrative and talking points.
- [Guides](../README.md#guides) — Extend the app with new agents, TTS, RAG, OpenTelemetry, etc., using GitHub Copilot.
- [Deploying to Azure](08-deploying-to-azure.md) — Push the whole thing to Azure Container Apps with `azd up`.

[← Back to README](../README.md)
