"""
tts.py — Text-to-Speech service using Azure AI Speech SDK.

Encapsulates all TTS configuration, authentication, and streaming synthesis
into a single class (`TTSService`) that can be used by the FastAPI route layer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

from azure.identity import DefaultAzureCredential
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .config import settings

logger = logging.getLogger(__name__)

# ─── Optional SDK import ──────────────────────────────────────────────────────

try:
    import azure.cognitiveservices.speech as speechsdk

    _SPEECH_SDK_AVAILABLE = True
except ImportError:
    speechsdk = None  # type: ignore[assignment]
    _SPEECH_SDK_AVAILABLE = False


# ─── Request model ────────────────────────────────────────────────────────────

class TTSRequest(BaseModel):
    text: str


# ─── PushAudioOutputStream callback ──────────────────────────────────────────

if _SPEECH_SDK_AVAILABLE:

    class _StreamCallback(speechsdk.audio.PushAudioOutputStreamCallback):
        """Bridges SDK audio push-stream chunks into an asyncio.Queue.

        The SDK calls ``write()`` on its own thread for each audio chunk and
        ``close()`` when synthesis completes.  We safely hand these over to the
        asyncio event loop via ``call_soon_threadsafe``.
        """

        def __init__(
            self,
            queue: asyncio.Queue,
            loop: asyncio.AbstractEventLoop,
        ) -> None:
            super().__init__()
            self._queue = queue
            self._loop = loop

        def write(self, audio_buffer: memoryview) -> int:
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait, bytes(audio_buffer)
            )
            return len(audio_buffer)

        def close(self) -> None:
            logger.info("[TTS] PushAudioOutputStream close() called")
            self._loop.call_soon_threadsafe(self._queue.put_nowait, None)


# ─── TTSService ───────────────────────────────────────────────────────────────

class TTSService:
    """Encapsulates Azure AI Speech TTS configuration and streaming synthesis.

    Usage::

        tts = TTSService()

        # Inside a FastAPI route:
        return tts.streaming_response("Hello, world!")
    """

    DEFAULT_VOICE = "en-US-Ava:DragonHDLatestNeural"

    def __init__(
        self,
        *,
        region: str = settings.azure_speech_region,
        resource_id: str = settings.azure_speech_resource_id,
        endpoint: str = settings.azure_speech_endpoint,
        voice: str = DEFAULT_VOICE,
    ) -> None:
        self._region = region
        self._resource_id = resource_id
        self._endpoint = endpoint
        self._voice = voice
        self._credential = DefaultAzureCredential()

    # ── Public API ────────────────────────────────────────────────────────

    def validate_config(self) -> None:
        """Raise HTTPException if the service is not properly configured."""
        if not self._region and not self._endpoint:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Azure Speech Service is not configured. "
                    "Set AZURE_SPEECH_REGION or AZURE_SPEECH_ENDPOINT."
                ),
            )
        if not self._resource_id:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Azure Speech Service is not configured. "
                    "Set AZURE_SPEECH_RESOURCE_ID."
                ),
            )
        if not _SPEECH_SDK_AVAILABLE:
            raise HTTPException(
                status_code=503,
                detail="azure-cognitiveservices-speech package is not installed.",
            )

    def streaming_response(self, text: str) -> StreamingResponse:
        """Return a ``StreamingResponse`` that streams synthesised audio/mpeg.

        Call ``validate_config()`` first (or let the route handler do it).
        """
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        speech_config = self._make_speech_config()
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3
        )
        speech_config.speech_synthesis_voice_name = self._voice

        # PushAudioOutputStream + callback: the SDK calls write() per audio
        # chunk on its own thread and close() when done.
        callback = _StreamCallback(queue, loop)
        push_stream = speechsdk.audio.PushAudioOutputStream(callback)
        audio_cfg = speechsdk.audio.AudioOutputConfig(stream=push_stream)
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config, audio_config=audio_cfg
        )

        # Wire up cancellation errors so they surface in the stream
        def on_canceled(evt):
            details = evt.result.cancellation_details
            logger.error(
                "[TTS] Synthesis canceled: %s — %s",
                details.reason,
                details.error_details,
            )
            loop.call_soon_threadsafe(
                queue.put_nowait,
                RuntimeError(f"Speech synthesis failed: {details.error_details}"),
            )

        # Belt-and-suspenders: push the None sentinel when synthesis completes.
        # The PushAudioOutputStreamCallback.close() *should* do this, but some
        # SDK versions only fire close() reliably when the result future is
        # consumed via .get().  This event is the authoritative "all audio has
        # been written" signal and ensures the HTTP response body always closes.
        def on_completed(evt):
            logger.info("[TTS] synthesis_completed event fired — closing audio stream")
            loop.call_soon_threadsafe(queue.put_nowait, None)

        synthesizer.synthesis_completed.connect(on_completed)
        synthesizer.synthesis_canceled.connect(on_canceled)
        synthesizer.speak_text_async(text)
        logger.info("[TTS] Streaming synthesis started for: '%s…'", text[:60])

        async def audio_stream() -> AsyncGenerator[bytes, None]:
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    if isinstance(item, RuntimeError):
                        raise item
                    yield item
            finally:
                # Keep SDK objects alive until the generator is fully consumed
                _ = synthesizer
                _ = push_stream  # noqa: F841

        return StreamingResponse(
            audio_stream(),
            media_type="audio/mpeg",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_auth_token(self) -> str:
        """Fetch an AAD access token formatted for the Speech SDK.

        The SDK expects:  ``aad#<resource_id>#<token>``
        """
        token = self._credential.get_token(
            "https://cognitiveservices.azure.com/.default"
        )
        return f"aad#{self._resource_id}#{token.token}"

    def _make_speech_config(self) -> "speechsdk.SpeechConfig":
        """Build a ``SpeechConfig`` using AAD token auth.

        Uses the configured endpoint (HTTPS) or falls back to the standard
        regional WSS host.
        """
        if self._endpoint:
            config = speechsdk.SpeechConfig(endpoint=self._endpoint)
        else:
            config = speechsdk.SpeechConfig(
                host=f"wss://{self._region}.tts.speech.microsoft.com"
            )
        config.authorization_token = self._get_auth_token()
        return config
