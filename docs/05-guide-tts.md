# Guide: Adding Text-to-Speech

[← Back to README](../README.md) | [Prerequisites & Setup](01-prerequisites-and-setup.md) | [Architecture Overview](02-architecture-overview.md)

This step-by-step guide walks you through adding **Azure AI Speech text-to-speech (TTS) narration** to every page of the storybook using **GitHub Copilot** to plan and implement the changes.

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

By the end of this guide, every page in the storybook will have a **play button** (🔊) that, when clicked:

1. Sends the page's text to a **new backend API endpoint**
2. The backend calls **Azure AI Speech** to synthesize the text into audio using a natural-sounding neural voice
3. The audio is **streamed back** to the browser and played for the user

**Page-specific behavior:**
| Page Type | Text Read Aloud |
|---|---|
| **Cover Page** | The story title |
| **Story Pages** | The full narrative text on that page |
| **"The End" Page** | Simply reads "The End" |

**Voice:** `en-US-Ava:DragonHDLatestNeural` — a high-quality neural voice optimized for expressive narration.

<!-- TODO: Add screenshot of a story page showing the play button -->

---

## Why This Matters

This guide demonstrates several important concepts:

| Concept | What It Shows |
|---|---|
| **Multi-Modal AI** | Adding a second AI modality (text → speech) alongside the existing text and image generation |
| **New API Endpoints** | Extending the FastAPI backend with a new endpoint and service integration |
| **Azure AI Speech SDK** | Using the Speech SDK with `DefaultAzureCredential` (AAD token auth, not API keys) |
| **Streaming Audio** | Streaming synthesized audio from the backend to the browser |
| **Frontend Audio Playback** | Playing streamed audio in the browser using Web APIs |
| **Copilot-Driven Development** | How GitHub Copilot can implement cross-cutting features that touch both backend and frontend |

---

## Before You Start

### 1. Complete Base Prerequisites

Ensure you've completed all steps in [Prerequisites & Setup](01-prerequisites-and-setup.md) and that the base application is working ([Running the Demo](03-running-the-demo.md)).

### 2. Provision Azure AI Speech Resource

> **This step is required for TTS functionality.** If you haven't already, follow the [Azure AI Speech Resource (TTS Guide Only)](01-prerequisites-and-setup.md#azure-ai-speech-resource-tts-guide-only) section in the Prerequisites guide.

You'll need these three values from your Speech resource:
- **Region** (e.g., `eastus`)
- **Endpoint** (e.g., `https://eastus.api.cognitive.microsoft.com/`)
- **Resource ID** (e.g., `/subscriptions/.../resourceGroups/.../providers/Microsoft.CognitiveServices/accounts/...`)

### 3. Add TTS Environment Variables

Open your `backend/.env` file and add the following variables:

```env
# Azure AI Speech (TTS)
AZURE_SPEECH_REGION=eastus
AZURE_SPEECH_ENDPOINT=https://eastus.api.cognitive.microsoft.com/
AZURE_SPEECH_RESOURCE_ID=/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<speech-resource-name>
```

> **Important:** Replace the placeholder values with your actual Speech resource details from the Azure Portal.

### 4. Verify Role Assignment

Ensure your Azure account has the **Cognitive Services Speech User** role on the Speech resource. The TTS implementation uses `DefaultAzureCredential` — not API keys — so this role assignment is what grants access.

```bash
# Verify your current Azure login
az account show

# If expired, log in again
az login
```

### 5. Verify VS Code Extensions

- [ ] **GitHub Copilot** and **GitHub Copilot Chat** — installed and signed in
- [ ] **VS Code AI Toolkit** — installed and enabled
- [ ] **Context7 MCP server** — configured and enabled in your VS Code MCP settings

### 6. Create a Working Branch

```bash
git checkout main
git pull origin main
git checkout -b my-tts-feature
```

> **Note:** If you've already completed the [Activity Page Agents guide](04-guide-activity-page-agents.md) and want to build on top of that work, you can branch from your activity pages branch instead:
> ```bash
> git checkout my-activity-pages
> git checkout -b my-all-features
> ```
> The `activity-page-agents-and-tts` reference branch shows both features combined.

---

## Step 1: Plan the Implementation (Plan Mode + Claude Opus)

In this step, you'll use GitHub Copilot's **Plan mode** with **Claude Opus** (or your preferred model) to analyze the codebase and produce a detailed implementation plan for TTS — without making any code changes.

### 1.1 Open GitHub Copilot Chat

- Open the **Copilot Chat** panel in VS Code (click the Copilot icon in the sidebar, or press `Ctrl+Shift+I` / `Cmd+Shift+I`).

### 1.2 Switch to Plan Mode

- At the top of the Copilot Chat panel, switch the mode to **"Plan"**.

### 1.3 Select Claude Opus as the Model

- Click the model selector and choose **Claude Opus** (or your preferred model).

<!-- TODO: Add screenshot showing Plan mode with Claude Opus selected -->

### 1.4 Paste the Sample Prompt

Copy and paste the following prompt into the Copilot Chat input:

> **Prompt:**
>
> Add an additional endpoint to the backend API that will receive text from a page of the story and perform a text-to-speech synthesis on it. This functionality should be called from the UI on each page. It should be presented as a "play" icon button that, when clicked, will call the API and will stream TTS back to the client and then play the audio for the user given the story text on that page. 
>
>Consider the following: 
>
> - Use Azure AI Speech TTS and the associated SDK for this implementation.
> - The text for the cover page should simply read the title of the story. 
> - The text for the last page (the "The End" page) should simply say, "The End". 
> - Use the following neural voice when performing the TTS synthesis: en-US-Ava:DragonHDLatestNeural. 
> - Ensure that proper audio streaming mechanisms are used.  Use `PushAudioOutputStream` from the SDK to receive chunks of audio and utilize an asyncio event loop to gather all chunks and stream them back to the client.  Ensure that proper delegates are setup and and events are communicated for `synthesis_completed` and `synthesis_canceled` events.
> - Ensure that the frontend properly adjusts the UI (play button should transition from "play" to "stop" when the audio stream finishes) when the audio stream has stopped.
> - Ensure that this functionality uses DefaultAzureCredential. 
> - Ensure that this functionality makes proper use of additional configuration. Additional configuration properties should be added to .env and .env.example for the following: AZURE_SPEECH_REGION, AZURE_SPEECH_ENDPOINT and AZURE_SPEECH_RESOURCE_ID. Utilize this example to implement the token acquisition:
>
> ```python
> def _get_auth_token() -> str:
>     """
>     Fetch an AAD access token and format it for the Speech SDK.
>     The SDK expects: aad#<resource_id>#<token>
>     """
>     token = _credential.get_token("https://cognitiveservices.azure.com/.default")
>     return f"aad#{SPEECH_RESOURCE_ID}#{token.token}"
>
> def _make_speech_config() -> speechsdk.SpeechConfig:
>     """Build a SpeechConfig using AAD token auth."""
>     if SPEECH_ENDPOINT:
>         config = speechsdk.SpeechConfig(endpoint=SPEECH_ENDPOINT)
>     else:
>         config = speechsdk.SpeechConfig(
>             host=f"wss://{SPEECH_REGION}.tts.speech.microsoft.com"
>         )
>     config.authorization_token = _get_auth_token()
>     return config
> ```

### 1.5 Review the Plan

Copilot (in Plan mode) will analyze the codebase and produce a plan covering:

- **Backend changes:**
  - New TTS service module (or additions to existing modules)
  - New API endpoint for TTS synthesis
  - Azure Speech SDK integration with `DefaultAzureCredential`
  - Token acquisition using the provided `_get_auth_token()` pattern
  - `SpeechConfig` creation using the provided `_make_speech_config()` pattern
  - Streaming audio response back to the client
  - New configuration properties in `config.py`

- **Frontend changes:**
  - Play button component or addition to `StoryPage.jsx`
  - Audio playback logic (fetching the audio stream and playing it)
  - Play button on `CoverPage`, regular `StoryPage`, and `FinalPage`
  - Appropriate text extraction for each page type

- **Configuration:**
  - New `.env` / `.env.example` variables: `AZURE_SPEECH_REGION`, `AZURE_SPEECH_ENDPOINT`, `AZURE_SPEECH_RESOURCE_ID`

- **Dependencies:**
  - `azure-cognitiveservices-speech` added to `requirements.txt`

**Take time to review the plan carefully.** Ask follow-up questions:

- *"How will the audio be streamed? Chunked HTTP response or WebSocket?"*
- *"What audio format will the Speech SDK output?"*
- *"How does the frontend handle the audio blob playback?"*
- *"What happens if the user clicks play on another page while audio is still playing?"*

> **Experiment:** Try refining the prompt:
> - *"Should there be a loading state on the play button while the audio is being fetched?"*
> - *"How should we handle errors if the Speech service is unavailable?"*

---

## Step 2: Implement with GitHub Copilot (Agent Mode + Claude Sonnet)

Once you're satisfied with the plan, switch to **Agent mode** to let Copilot implement the changes.

### 2.1 Switch to Agent Mode

- Change the mode at the top of the Copilot Chat panel from **"Plan"** to **"Agent"**.

### 2.2 Select Claude Sonnet as the Model

- Click the model selector and choose **Claude Sonnet** (or your preferred model).

<!-- TODO: Add screenshot showing Agent mode with Claude Sonnet selected -->

### 2.3 Run the Implementation

You can either:

**Option A:** Paste the same TTS prompt used in Step 1.

**Option B:** Reference the plan:
> *"Implement the plan from our previous conversation for adding TTS functionality."*

### 2.4 Watch Copilot Work

Copilot in Agent mode will make changes across multiple files:

1. **Backend — New TTS service:**
   - Create a TTS module (e.g., `backend/app/tts.py` or similar)
   - Implement `_get_auth_token()` using `DefaultAzureCredential` with the provided code pattern
   - Implement `_make_speech_config()` using the provided code pattern
   - Set the voice to `en-US-Ava:DragonHDLatestNeural`
   - Handle audio synthesis and streaming

2. **Backend — New API endpoint:**
   - Add a new endpoint to `main.py` (e.g., `POST /api/tts`)
   - Accept text input, call the TTS service, return streaming audio

3. **Backend — Configuration:**
   - Add `AZURE_SPEECH_REGION`, `AZURE_SPEECH_ENDPOINT`, and `AZURE_SPEECH_RESOURCE_ID` to `config.py`
   - Update `.env.example` with the new variables

4. **Backend — Dependencies:**
   - Add `azure-cognitiveservices-speech` to `requirements.txt`

5. **Frontend — Play button:**
   - Add a play icon/button to each page component (`CoverPage`, `StoryPage`, `FinalPage`)
   - Implement the API call to the new TTS endpoint
   - Handle audio playback (likely using the `Audio` Web API or an `<audio>` element)
   - Set the appropriate text for each page type:
     - Cover: story title
     - Story pages: narrative text
     - "The End": literal "The End"

6. **Frontend — Styling:**
   - Style the play button to fit the storybook aesthetic

> **Tip:** Let Copilot make all the changes, then review them file-by-file before accepting.

### 2.5 Accept the Changes

Review each file change:
- Verify the `_get_auth_token()` and `_make_speech_config()` implementations match the provided patterns
- Check that the voice name is set correctly: `en-US-Ava:DragonHDLatestNeural`
- Ensure `DefaultAzureCredential` is used (not API keys)
- Confirm the frontend correctly sends different text for cover, story, and "The End" pages

---

## Step 3: Review and Test

### 3.1 Install New Dependencies

The TTS feature requires the Azure Speech SDK Python package:

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt
```

> **Note:** The `azure-cognitiveservices-speech` package is relatively large and may take a minute to install.

### 3.2 Verify Environment Variables

Double-check that your `backend/.env` includes:

```env
AZURE_SPEECH_REGION=<your-region>
AZURE_SPEECH_ENDPOINT=<your-endpoint>
AZURE_SPEECH_RESOURCE_ID=<your-resource-id>
```

### 3.3 Restart the Application

```bash
# Restart the backend
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# The frontend should auto-reload; if not:
cd frontend
npm run dev
```

### 3.4 Test TTS on Each Page Type

1. **Generate a story** — Fill in the form and create a story as usual.
2. **Test the Cover Page:**
   - Navigate to the cover page
   - Click the play button (🔊)
   - Verify you hear the **story title** read aloud
3. **Test a Story Page:**
   - Navigate to any story page (pages 1–N)
   - Click the play button
   - Verify you hear the **narrative text** for that page read aloud
4. **Test the "The End" Page:**
   - Navigate to the last page
   - Click the play button
   - Verify you hear **"The End"** read aloud

### 3.5 Test Edge Cases

- **Click play while audio is playing** — Does it stop the current audio and start new audio, or does it queue?
- **Navigate away while audio is playing** — Does the audio stop when you leave the page?
- **Rapid clicking** — Click the play button multiple times quickly. The UI should handle this gracefully.
- **Network error** — Temporarily disconnect from the internet and click play. The UI should show an appropriate error state.

<!-- TODO: Add screenshot of the play button on a story page -->

### 3.6 Compare with the Reference Branch (Optional)

```bash
# View diff against reference
git diff my-tts-feature..origin/story-tts

# Or check out the reference to test it
git stash
git checkout story-tts
# Test...
git checkout my-tts-feature
git stash pop
```

---

## What to Look For

After the implementation is complete, review the code to understand these key patterns:

### AAD Token Authentication

The TTS implementation uses Azure Active Directory (AAD) tokens instead of API keys. This is the recommended pattern for production applications:

```python
def _get_auth_token() -> str:
    """
    Fetch an AAD access token and format it for the Speech SDK.
    The SDK expects: aad#<resource_id>#<token>
    """
    token = _credential.get_token("https://cognitiveservices.azure.com/.default")
    return f"aad#{SPEECH_RESOURCE_ID}#{token.token}"
```

**Key points:**
- `_credential` is a `DefaultAzureCredential` instance — the same auth pattern used by the rest of the application
- The Speech SDK expects tokens in a specific format: `aad#<resource_id>#<token>`
- The scope `https://cognitiveservices.azure.com/.default` is the standard scope for Cognitive Services

### SpeechConfig Construction

```python
def _make_speech_config() -> speechsdk.SpeechConfig:
    """Build a SpeechConfig using AAD token auth."""
    if SPEECH_ENDPOINT:
        config = speechsdk.SpeechConfig(endpoint=SPEECH_ENDPOINT)
    else:
        config = speechsdk.SpeechConfig(
            host=f"wss://{SPEECH_REGION}.tts.speech.microsoft.com"
        )
    config.authorization_token = _get_auth_token()
    return config
```

**Key points:**
- Prefers the explicit endpoint when available; falls back to constructing the WebSocket URL from the region
- The authorization token is set after creating the config
- This pattern separates the connection details from the authentication, making it flexible for different deployment scenarios

### Neural Voice Selection

The implementation uses `en-US-Ava:DragonHDLatestNeural` — a high-definition neural voice designed for expressive, natural-sounding narration. This is ideal for children's stories as it:
- Supports expressive prosody
- Produces high-quality audio output
- Handles varied sentence structures and emotions naturally

### Audio Streaming

Look at how the backend streams the synthesized audio to the frontend:
- The API endpoint should return a streaming response (chunked transfer encoding)
- The frontend should handle the audio blob and play it using the Web Audio API or an `<audio>` element
- Consider whether the implementation uses pull or push streaming from the Speech SDK

### Frontend Audio Playback

Check how the play button component:
- Extracts the correct text for each page type (title, narrative, "The End")
- Makes the API call to the TTS endpoint
- Creates an audio blob from the response
- Plays the audio and manages the playing/stopped state
- Handles concurrent play requests

---

## Reference Branch

The `story-tts` branch contains a complete working implementation of this feature.

```bash
# View the reference implementation
git checkout story-tts

# Return to your working branch
git checkout my-tts-feature
```

> **Combined branch:** The `activity-page-agents-and-tts` branch includes both the activity page agents and TTS functionality together. If you've already completed the [Activity Page Agents guide](04-guide-activity-page-agents.md), this branch shows how both features coexist.

---

## Troubleshooting

### "Authentication failed" or "401 Unauthorized" from the Speech SDK

1. **Verify your Azure login:** Run `az account show` — if expired, run `az login`.
2. **Check role assignment:** Ensure your account has the **Cognitive Services Speech User** role on the Speech resource.
3. **Verify resource ID:** The `AZURE_SPEECH_RESOURCE_ID` in `.env` must be the full Azure resource ID (starts with `/subscriptions/...`).
4. **Check region:** The `AZURE_SPEECH_REGION` must match the actual region of your Speech resource.

### No audio plays but no errors appear

1. **Check the browser console** — Look for errors in the Developer Tools console (F12).
2. **Check the network tab** — Verify the TTS API call returns 200 and includes audio data.
3. **Check audio format** — Ensure the backend is returning audio in a format the browser can play (e.g., `audio/wav`, `audio/mpeg`).
4. **Check browser permissions** — Some browsers block audio autoplay. The user must interact with the page (clicking the play button counts) before audio can play.

### `ModuleNotFoundError: No module named 'azure.cognitiveservices.speech'`

Install the Speech SDK:
```bash
cd backend
source .venv/bin/activate
pip install azure-cognitiveservices-speech
```

Or reinstall all dependencies:
```bash
pip install -r requirements.txt
```

### The play button doesn't appear

1. Verify that the frontend components (`CoverPage`, `StoryPage`, `FinalPage`) were updated with the play button.
2. Check that the button isn't being hidden by CSS — inspect the element in Developer Tools.
3. Restart the Vite dev server if changes aren't reflected.

### Copilot didn't include the `_get_auth_token` / `_make_speech_config` patterns

If Copilot's implementation doesn't match the provided token acquisition pattern:
1. Ask Copilot to refactor: *"Please update the TTS authentication to use the `_get_auth_token()` and `_make_speech_config()` patterns I provided in the original prompt."*
2. Or manually verify the implementation matches the pattern from the prompt.

### Audio quality sounds robotic or low quality

Ensure the voice is set to `en-US-Ava:DragonHDLatestNeural`. If a different voice was used, update the Speech SDK configuration to use this specific voice name.

---

## Next Steps

- If you haven't already, try the [Activity Page Agents guide](04-guide-activity-page-agents.md) to add Look & Find and Character Glossary pages.
- Add [OpenTelemetry observability](07.a-guide-otel-observability-ai-toolkit.md) to trace the full agent workflow in VS Code via AI Toolkit, or use the [Aspire Dashboard variant](07.b-guide-otel-observability-aspire.md) for a browser-based view.
- Experiment further: try different neural voices, add a voice selector to the UI, or add TTS to the activity pages.
- Check out the `activity-page-agents-and-tts` branch to see pre-built functionality of the activity page, character glossary and tts features working together.

[← Back to README](../README.md)
