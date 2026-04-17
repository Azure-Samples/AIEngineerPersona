import { useState, useRef, useCallback } from 'react';
import styles from './StoryPage.module.css';

/* ─── TTS hook ──────────────────────────────────────────────────────────── */

function useTTS() {
  const [isPlaying, setIsPlaying] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const stateRef = useRef({ audio: null, mediaSource: null });

  const cleanup = useCallback(() => {
    const { audio, mediaSource } = stateRef.current;
    if (audio) {
      audio.pause();
      if (audio._blobUrl) URL.revokeObjectURL(audio._blobUrl);
    }
    if (mediaSource && mediaSource.readyState === 'open') {
      try { mediaSource.endOfStream(); } catch (_) {}
    }
    stateRef.current = { audio: null, mediaSource: null };
    setIsPlaying(false);
    setIsLoading(false);
  }, []);

  const play = useCallback(async (text) => {
    // Toggle off if already playing
    if (stateRef.current.audio) {
      cleanup();
      return;
    }

    setIsLoading(true);
    try {
      const ms  = new MediaSource();
      const url = URL.createObjectURL(ms);
      const audio = new Audio(url);
      audio._blobUrl = url;
      stateRef.current = { audio, mediaSource: ms };

      audio.addEventListener('ended', cleanup, { once: true });
      audio.addEventListener('error', cleanup, { once: true });
      // Some browsers (especially Safari) fire 'pause' instead of 'ended'
      // when a MediaSource stream ends. Guard with audio.ended so this
      // doesn't trigger on a normal user-initiated pause.
      audio.addEventListener('pause', () => { if (audio.ended) cleanup(); });

      await new Promise((resolve, reject) => {
        ms.addEventListener('sourceopen', async () => {
          let sb;
          try {
            sb = ms.addSourceBuffer('audio/mpeg');
          } catch (e) { reject(e); return; }

          // Serialise appendBuffer calls — the SourceBuffer can only handle one at a time
          const queue = [];
          let busy = false;
          let streamDone = false;

          const tryEndStream = () => {
            if (streamDone && !busy && queue.length === 0 && ms.readyState === 'open') {
              try { ms.endOfStream(); } catch (_) {}
            }
          };

          const flush = () => {
            if (busy || !queue.length) return;
            const chunk = queue.shift();
            busy = true;
            sb.appendBuffer(chunk);
          };

          sb.addEventListener('updateend', () => {
            busy = false;
            if (queue.length > 0) {
              flush();
            } else {
              tryEndStream();
            }
          });

          const push = (chunk) => { queue.push(chunk); flush(); };

          // Start playback as soon as the browser has enough data
          audio.addEventListener('canplay', () => {
            setIsLoading(false);
            setIsPlaying(true);
            audio.play().catch(console.error);
          }, { once: true });

          // Fetch the streaming TTS response
          let res;
          try {
            res = await fetch('/api/tts', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ text }),
            });
          } catch (e) { reject(e); return; }

          if (!res.ok) { reject(new Error(`TTS ${res.status}`)); return; }

          // Pipe response body chunks into the SourceBuffer, then signal end-of-stream.
          // Inline (no detached IIFE) so errors propagate to reject() and
          // resolve() is only called after all chunks are consumed.
          const reader = res.body.getReader();
          try {
            while (true) {
              const { done, value } = await reader.read();
              if (done) {
                streamDone = true;
                tryEndStream(); // in case queue already drained before this point
                break;
              }
              push(value);
            }
            resolve(); // stream fully consumed — settle the outer promise
          } catch (e) {
            reject(e);
          }
        }, { once: true });

        ms.addEventListener('error', () => reject(new Error('MediaSource error')), { once: true });
      });
    } catch (err) {
      console.error('[TTS] Error:', err);
      cleanup();
    }
  }, [cleanup]);

  return { isPlaying, isLoading, play };
}

/* ─── Play button ───────────────────────────────────────────────────────── */

function PlayButton({ text }) {
  const { isPlaying, isLoading, play } = useTTS();
  return (
    <button
      className={styles.playBtn}
      onClick={() => play(text)}
      disabled={isLoading}
      title={isPlaying ? 'Stop reading' : 'Read aloud'}
      aria-label={isPlaying ? 'Stop reading' : 'Read aloud'}
    >
      {isLoading
        ? <span className={styles.playSpinner} />
        : isPlaying ? '⏹' : '▶'}
    </button>
  );
}

/** Cover page — shown as "page 0" before the story pages */
export function CoverPage({ story }) {
  const charNames = [
    ...(story.pages?.[0]?.characters_present ?? []),
  ].slice(0, 6);

  return (
    <div className={styles.coverPage}>
      {/* Illustration area */}
      <div className={styles.coverImageArea}>
        {story.cover_image_url ? (
          <img src={story.cover_image_url} alt="Book cover" className={styles.coverImage} />
        ) : (
          <div className={styles.coverImagePlaceholder}>📖</div>
        )}
        {/* Title overlay on the image */}
        <div className={styles.coverOverlay}>
          <h2 className={styles.coverTitle}>{story.title}</h2>
          {charNames.length > 0 && (
            <p className={styles.coverCharacters}>Featuring: {charNames.join(', ')}</p>
          )}
        </div>
      </div>

      {/* Moral tagline below the image */}
      <div className={styles.coverMoralArea}>
        <div className={styles.coverMoral}>
          <em>"{story.moral_summary}"</em>
        </div>
        <PlayButton text={story.title} />
      </div>
    </div>
  );
}

/** Final / "The End" page — shown after all story pages */
export function FinalPage({ story }) {
  if (story.the_end_image_url) {
    return (
      <div className={styles.finalPage}>
        <div className={styles.finalImageArea}>
          <img src={story.the_end_image_url} alt="The End" className={styles.finalImage} />
          <div className={styles.finalPlayOverlay}>
            <PlayButton text="The End" />
          </div>
        </div>
      </div>
    );
  }

  // Fallback when image isn't available
  return (
    <div className={styles.finalPage}>
      <div className={styles.finalEmoji}>⭐</div>
      <h3 className={styles.finalTitle}>The End</h3>
      <p className={styles.finalMoral}>{story.moral_summary}</p>
      {story.review_notes && story.review_notes !== 'Story approved with no issues.' && (
        <p className={styles.finalNotes}>{story.review_notes}</p>
      )}
      <div className={styles.finalFallbackPlay}>
        <PlayButton text="The End" />
      </div>
    </div>
  );
}

/** An individual story page with illustration + narrative text */
export default function StoryPage({ page, totalPages }) {
  return (
    <div className={styles.page}>
      {/* Illustration */}
      <div className={styles.imageWrapper}>
        {page.image_url ? (
          <img
            src={page.image_url}
            alt={`Illustration for page ${page.page_number}`}
            className={styles.image}
          />
        ) : (
          <div className={styles.imagePlaceholder}>
            <span>🖼️</span>
            <span>
              {page.scene_description
                ? page.scene_description.slice(0, 120) + '…'
                : 'Illustration coming soon'}
            </span>
          </div>
        )}
        <div className={styles.pageBadge}>
          Page {page.page_number} of {totalPages}
        </div>
      </div>

      {/* Narrative text */}
      <div className={styles.textArea}>
        <div className={styles.textRow}>
          <p className={styles.storyText}>{page.text}</p>
          <PlayButton text={page.text} />
        </div>
        {page.characters_present?.length > 0 && (
          <div className={styles.characterTags}>
            {page.characters_present.map((c, i) => (
              <span key={i} className={styles.tag}>{c}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** Look & Find activity page — appended after "The End" */
export function LookAndFindPage({ activity }) {
  if (!activity) return null;
  return (
    <div className={styles.bonusPage}>
      <div className={styles.bonusHeader}>
        <span className={styles.bonusIcon}>🔎</span>
        <h3 className={styles.bonusTitle}>Look &amp; Find!</h3>
      </div>
      <p className={styles.bonusInstructions}>{activity.instructions}</p>
      <div className={styles.lookAndFindList}>
        {activity.items?.map((item, i) => (
          <div key={i} className={styles.lookAndFindItem}>
            <div className={styles.lookAndFindNumber}>{i + 1}</div>
            <div className={styles.lookAndFindContent}>
              <div className={styles.lookAndFindName}>
                <strong>{item.item_name}</strong>
                <span className={styles.lookAndFindPage}>Page {item.page_number}</span>
              </div>
              <p className={styles.lookAndFindDesc}>{item.item_description}</p>
              {item.hint && (
                <p className={styles.lookAndFindHint}>
                  <em>Hint: {item.hint}</em>
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Character Glossary page — appended after "The End" */
export function CharacterGlossaryPage({ glossary }) {
  if (!glossary) return null;
  return (
    <div className={styles.bonusPage}>
      <div className={styles.bonusHeader}>
        <span className={styles.bonusIcon}>📖</span>
        <h3 className={styles.bonusTitle}>Meet the Characters!</h3>
      </div>
      <div className={styles.glossaryList}>
        {glossary.entries?.map((entry, i) => (
          <div key={i} className={styles.glossaryEntry}>
            <div className={styles.glossaryEntryHeader}>
              <span className={styles.glossaryName}>{entry.name}</span>
              <span className={styles.glossaryRole}>{entry.role}</span>
            </div>
            <p className={styles.glossaryDescription}>{entry.description}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
