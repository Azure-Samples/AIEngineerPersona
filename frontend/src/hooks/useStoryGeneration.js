/**
 * useStoryGeneration — custom React hook
 *
 * Manages the full story generation lifecycle:
 *  1. POST the StoryRequest to /api/generate-story
 *  2. Consume the SSE response stream
 *  3. Emit granular progress events to the UI
 *  4. Set the final StoryResponse when complete
 */

import { useState, useRef, useCallback } from 'react';

const INITIAL_PROGRESS = [];

export function useStoryGeneration() {
  const [story, setStory]             = useState(null);
  const [progress, setProgress]       = useState(INITIAL_PROGRESS);
  const [details, setDetails]         = useState([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError]             = useState(null);
  const abortControllerRef            = useRef(null);

  const generate = useCallback(async (storyRequest) => {
    // Reset state, pre-seeding orchestrator as active so the progress tracker
    // shows it working immediately — before the first SSE event arrives.
    setStory(null);
    setDetails([]);
    setProgress([{
      executor_id: 'orchestrator',
      status: 'started',
      label: 'Orchestrator',
      message: 'Creating the story outline...',
      timestamp: Date.now(),
    }]);
    setError(null);
    setIsGenerating(true);

    // Allow cancellation
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response = await fetch('/api/generate-story', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(storyRequest),
        signal: controller.signal,
      });

      if (!response.ok) {
        const errText = await response.text();
        throw new Error(`Server error ${response.status}: ${errText}`);
      }

      // Read the SSE stream.
      // SSE wire format: each message is a block of "field: value" lines
      // terminated by a blank line. sse-starlette sends:
      //   event: progress\ndata: {"executor_id":...}\n\n
      // We accumulate currentEvent + currentData across lines, then dispatch
      // when we hit the blank-line message separator.
      const reader  = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer      = '';
      let currentEvent = '';
      let currentData  = '';

      const dispatch = () => {
        if (!currentData) return;
        const raw = currentData.trim();
        if (!raw || raw === '[DONE]') return;
        let data;
        try { data = JSON.parse(raw); } catch { return; }
        handleSsePayload(currentEvent, data, setProgress, setDetails, setStory, setError);
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          dispatch(); // flush any trailing message
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // keep incomplete last line

        for (const line of lines) {
          if (line === '' || line === '\r') {
            // Blank line = end of one SSE message — dispatch and reset
            dispatch();
            currentEvent = '';
            currentData  = '';
          } else if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            currentData = line.slice(5).trim();
          }
          // ignore id: and comment lines (:)
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') return; // user cancelled — silently ignore
      setError(err.message || 'An unexpected error occurred.');
    } finally {
      setIsGenerating(false);
    }
  }, []);

  const cancel = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setIsGenerating(false);
  }, []);

  const reset = useCallback(() => {
    cancel();
    setStory(null);
    setProgress([]);
    setDetails([]);
    setError(null);
  }, [cancel]);

  return { story, progress, details, isGenerating, error, generate, cancel, reset };
}

// ─── SSE payload handler ──────────────────────────────────────────────────────

/**
 * Dispatch a single parsed SSE message.
 * @param {string} eventType  - value from the SSE `event:` line
 * @param {object} data       - already JSON.parsed value from the SSE `data:` line
 */
function handleSsePayload(eventType, data, setProgress, setDetails, setStory, setError) {

  switch (eventType) {
    case 'progress':
      setProgress(prev => {
        const existingIdx = prev.findIndex(p => p.executor_id === data.executor_id && p.status === 'started');
        if (data.status === 'completed' && existingIdx !== -1) {
          // Update the existing started entry to completed in-place
          const updated = [...prev];
          updated[existingIdx] = { ...updated[existingIdx], status: 'completed', message: data.message };
          return updated;
        }
        if (data.status === 'started') {
          if (existingIdx !== -1) {
            // Replace the pre-seeded/existing started entry rather than duplicating
            const updated = [...prev];
            updated[existingIdx] = { ...data, timestamp: Date.now() };
            return updated;
          }
          return [...prev, { ...data, timestamp: Date.now() }];
        }
        return prev;
      });
      break;

    case 'revision':
      setProgress(prev => [
        ...prev,
        {
          executor_id: 'revision',
          status: 'revision',
          label: `Revision Round ${data.revision_round}`,
          message: data.message,
          timestamp: Date.now(),
        },
      ]);
      break;

    case 'detail':
      setDetails(prev => [
        ...prev,
        { ...data, timestamp: Date.now() },
      ]);
      break;

    case 'complete':
      setStory(data.story);
      break;

    case 'error':
      setError(data.message || 'An error occurred during story generation.');
      break;

    default:
      break;
  }
}
