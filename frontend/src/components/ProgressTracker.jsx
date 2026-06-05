import { Fragment, useMemo, useState } from 'react';
import styles from './ProgressTracker.module.css';

/* ─── Static step definitions ─────────────────────────────────────────────── */

const BASE_WORKFLOW_STEPS = [
  { id: 'orchestrator',    icon: '📋', label: 'Orchestrator',    hint: 'Planning the story outline...' },
  { id: 'story_architect', icon: '✍️',  label: 'Story Architect', hint: 'Writing the story pages...' },
  { id: 'art_director',    icon: '🎨', label: 'Art Director',    hint: 'Generating illustrations...' },
  { id: 'story_reviewer',  icon: '🔍', label: 'Story Reviewer',  hint: 'Reviewing for quality...' },
  { id: 'decision',        icon: '⚖️',  label: 'Decision',       hint: 'Finalising the story...' },
];

const LOOK_AND_FIND_STEP    = { id: 'look_and_find',      icon: '🔎', label: 'Look & Find',       hint: 'Creating the Look & Find activity page...' };
const CHARACTER_GLOSSARY_STEP = { id: 'character_glossary', icon: '📖', label: 'Character Glossary', hint: 'Writing the Character Glossary...' };
const FINAL_ASSEMBLY_STEP   = { id: 'final_assembly',      icon: '📦', label: 'Final Assembly',    hint: 'Assembling the final story...' };

function buildWorkflowSteps(bonusAgents) {
  const steps = [...BASE_WORKFLOW_STEPS];
  if (bonusAgents?.lookAndFind)      steps.push(LOOK_AND_FIND_STEP);
  if (bonusAgents?.characterGlossary) steps.push(CHARACTER_GLOSSARY_STEP);
  steps.push(FINAL_ASSEMBLY_STEP);
  return steps;
}

/* ─── Helpers ─────────────────────────────────────────────────────────────── */

function resolveStepStatus(stepId, progress, details = []) {
  const progEvts = progress.filter(p => p.executor_id === stepId);

  // Use detail events as a more granular active/revision signal.
  // If the most recent detail event is one that indicates active processing
  // (i.e. no response_received has arrived yet after it), treat the step
  // as active — this covers revision loops where the framework emits a
  // "revision" SSE rather than a "progress/started" for orchestrator.
  const stepDetails = details.filter(d => d.executor_id === stepId);
  if (stepDetails.length > 0) {
    const lastDetail = stepDetails.at(-1);
    const activeTypes    = new Set(['executor_started', 'revision_started', 'prompt_sent', 'page_content', 'image_started', 'image_queued', 'images_batch_started', 'wikipedia_fetched', 'wikipedia_not_found']);
    const completedTypes = new Set(['response_received', 'image_completed', 'image_failed', 'auto_approved']);
    if (activeTypes.has(lastDetail.detail_type)) {
      return lastDetail.detail_type === 'revision_started' ? 'revision' : 'active';
    }
    if (completedTypes.has(lastDetail.detail_type) && progEvts.length === 0) {
      return 'completed';
    }
  }

  if (progEvts.length === 0) return 'pending';
  const last = progEvts.at(-1);
  if (last.status === 'completed') return 'completed';
  if (last.status === 'started')   return 'active';
  return 'pending';
}

/* ─── Detail sub-components ───────────────────────────────────────────────── */

function PromptBlock({ text }) {
  const [expanded, setExpanded] = useState(false);
  if (!text) return null;
  const preview = text.length > 300 ? text.slice(0, 300) + '…' : text;
  return (
    <div className={styles.promptBlock}>
      <div className={styles.detailLabel}>Prompt sent</div>
      <pre className={styles.promptText}>{expanded ? text : preview}</pre>
      {text.length > 300 && (
        <button className={styles.toggleBtn} onClick={() => setExpanded(e => !e)}>
          {expanded ? 'Show less ▲' : 'Show full prompt ▼'}
        </button>
      )}
    </div>
  );
}

function AutoApprovedBlock() {
  return (
    <div className={`${styles.responseBlock} ${styles.approved}`}>
      <div className={styles.detailLabel}>Auto-approved — story reviewer skipped</div>
    </div>
  );
}

function ResponseBlock({ data, executorId }) {
  if (!data) return null;
  if (executorId === 'orchestrator') {
    return (
      <div className={styles.responseBlock}>
        <div className={styles.detailLabel}>✅ Outline created</div>
        <div className={styles.responseRow}><span className={styles.responseKey}>Title</span><span>{data.title}</span></div>
        <div className={styles.responseRow}><span className={styles.responseKey}>Pages</span><span>{data.page_count}</span></div>
        <div className={styles.responseRow}><span className={styles.responseKey}>Characters</span><span>{data.characters?.join(', ')}</span></div>
        <div className={styles.responseRow}><span className={styles.responseKey}>Plot</span><span>{data.plot_summary}</span></div>
      </div>
    );
  }
  if (executorId === 'story_architect') {
    return (
      <div className={styles.responseBlock}>
        <div className={styles.detailLabel}>✅ Draft complete</div>
        <div className={styles.responseRow}><span className={styles.responseKey}>Title</span><span>{data.title}</span></div>
        <div className={styles.responseRow}><span className={styles.responseKey}>Pages</span><span>{data.page_count}</span></div>
        <div className={styles.responseRow}><span className={styles.responseKey}>Moral</span><span>{data.moral_summary}</span></div>
      </div>
    );
  }
  if (executorId === 'story_reviewer') {
    const approved = data.approved;
    return (
      <div className={`${styles.responseBlock} ${approved ? styles.approved : styles.rejected}`}>
        <div className={styles.detailLabel}>{approved ? '✅ Story approved' : '⚠️ Revisions requested'}</div>
        {!approved && data.issues?.map((issue, i) => (
          <div key={i} className={styles.issueRow}>
            <span className={styles.issueCategory}>{issue.category}</span>
            <span>{issue.description}</span>
          </div>
        ))}
        {!approved && data.revision_instructions && (
          <div className={styles.revisionInstructions}>{data.revision_instructions}</div>
        )}
      </div>
    );
  }
  if (executorId === 'look_and_find') {
    return (
      <div className={styles.responseBlock}>
        <div className={styles.detailLabel}>Activity created — {data.item_count} items to find</div>
        {data.items?.map((item, i) => (
          <div key={i} className={styles.responseRow}>
            <span className={styles.responseKey}>Page {item.page}</span>
            <span>{item.name}</span>
          </div>
        ))}
      </div>
    );
  }
  if (executorId === 'character_glossary') {
    return (
      <div className={styles.responseBlock}>
        <div className={styles.detailLabel}>Glossary complete — {data.entry_count} characters</div>
        {data.characters?.map((name, i) => (
          <div key={i} className={styles.responseRow}>
            <span className={styles.responseKey}>{name}</span>
          </div>
        ))}
      </div>
    );
  }
  return null;
}

function ExecutorStartedBlock({ data }) {
  if (!data) return null;
  const isFullMode = data.wikipedia_mode === 'full';
  return (
    <div className={styles.responseBlock}>
      <div className={styles.detailLabel}>Story request received</div>
      {isFullMode ? (
        <div className={styles.responseRow}>
          <span className={styles.responseKey}>Mode</span>
          <span>Full Wikipedia Story — characters, setting &amp; plot derived from article</span>
        </div>
      ) : (
        <>
          <div className={styles.responseRow}><span className={styles.responseKey}>Hero</span><span>{data.main_character}</span></div>
          {data.supporting_characters?.length > 0 && (
            <div className={styles.responseRow}><span className={styles.responseKey}>Also</span><span>{data.supporting_characters.join(', ')}</span></div>
          )}
          <div className={styles.responseRow}><span className={styles.responseKey}>Setting</span><span>{data.setting}</span></div>
          <div className={styles.responseRow}><span className={styles.responseKey}>Moral</span><span>{data.moral}</span></div>
          <div className={styles.responseRow}><span className={styles.responseKey}>Problem</span><span>{data.main_problem}</span></div>
        </>
      )}
    </div>
  );
}

function WikipediaFetchedBlock({ data }) {
  if (!data) return null;
  const isFullMode = data.mode === 'full';
  return (
    <div className={styles.responseBlock}>
      <div className={styles.detailLabel}>Wikipedia content retrieved</div>
      <div className={styles.responseRow}>
        <span className={styles.responseKey}>Topic</span>
        <span>{data.resolved_title}</span>
      </div>
      <div className={styles.responseRow}>
        <span className={styles.responseKey}>Mode</span>
        <span>{isFullMode
          ? 'Full — story created entirely from Wikipedia'
          : 'Influence — blended with your story details'}
        </span>
      </div>
      <div className={styles.responseRow}>
        <span className={styles.responseKey}>Content</span>
        <span>{data.extract_length?.toLocaleString()} characters fetched</span>
      </div>
    </div>
  );
}

function WikipediaNotFoundBlock({ data }) {
  if (!data) return null;
  return (
    <div className={`${styles.responseBlock} ${styles.rejected}`}>
      <div className={styles.detailLabel}>Wikipedia topic not found: &quot;{data.topic}&quot;</div>
      <div className={styles.revisionInstructions}>
        The story will be generated without Wikipedia content.
      </div>
    </div>
  );
}

function RevisionStartedBlock({ data }) {
  if (!data) return null;
  return (
    <div className={`${styles.responseBlock} ${styles.rejected}`}>
      <div className={styles.detailLabel}>🔄 Revision #{data.revision_number} requested</div>
      {data.revision_instructions && (
        <div className={styles.revisionInstructions}>{data.revision_instructions}</div>
      )}
    </div>
  );
}

/* ─── Reviewer per-call checklist ──────────────────────────────────────────
 * Renders the StoryReviewer's parallel sub-call progress as a checklist.
 * Seeds rows from the prompt_sent.data.calls array (every expected call in
 * `pending` state immediately) and walks review_call_started /
 * review_call_completed / review_call_failed events to update each row.
 * One row per call_id; the latest event for a row wins.
 *
 * Visuals:
 * - Cover, Page N, and "The End" rows use a tiny thumbnail of the actual
 *   generated image (looked up by page_number slot: cover=0, page=N,
 *   the_end=page_count+1).
 * - Story text and Cross-page consistency rows have no icon at all.
 * - A single grouped description appears above all image rows (cover/page/
 *   the_end). Story text and Cross-page consistency rows each get their own
 *   inline description below the row header.
 */

const IMAGE_KINDS = new Set(['cover', 'page', 'the_end']);

const REVIEWER_GROUP_DESCRIPTION_IMAGES =
  'Checking each illustration for consistency with the page text, character likeness, and age-appropriate visuals.';

const REVIEWER_ROW_DESCRIPTIONS = {
  text:       'Reviewing the story text for narrative coherence, age-appropriate vocabulary, and faithful integration of the moral.',
  cross_page: 'Comparing characters across all pages to ensure they look consistent throughout the book.',
};

function ReviewerCallList({ promptEvt, callEvts, imageUrlByPageNumber = {} }) {
  const [expandedCallId, setExpandedCallId] = useState(null);
  const seedCalls = promptEvt?.data?.calls;
  if (!Array.isArray(seedCalls) || seedCalls.length === 0) return null;

  const pageCount = promptEvt?.data?.page_count ?? 0;

  // Walk lifecycle events in order; latest event for a call_id wins.
  const stateByCallId = {};
  for (const seed of seedCalls) {
    if (!seed?.call_id) continue;
    stateByCallId[seed.call_id] = {
      ...seed,
      status: 'pending',
      passed: null,
      issue_count: 0,
      issues: [],
      error: null,
    };
  }
  for (const ev of callEvts) {
    const cid = ev.data?.call_id;
    if (!cid || !stateByCallId[cid]) continue;
    if (ev.detail_type === 'review_call_started') {
      stateByCallId[cid] = { ...stateByCallId[cid], status: 'running' };
    } else if (ev.detail_type === 'review_call_completed') {
      stateByCallId[cid] = {
        ...stateByCallId[cid],
        status: 'completed',
        passed: ev.data?.passed === true,
        issue_count: ev.data?.issue_count || 0,
        issues: Array.isArray(ev.data?.issues) ? ev.data.issues : [],
      };
    } else if (ev.detail_type === 'review_call_failed') {
      stateByCallId[cid] = {
        ...stateByCallId[cid],
        status: 'failed',
        error: ev.data?.error || 'unknown error',
      };
    }
  }

  const rows = seedCalls.map(s => stateByCallId[s.call_id]).filter(Boolean);
  const total = rows.length;
  const completedCount = rows.filter(r => r.status === 'completed' || r.status === 'failed').length;

  const renderStatus = (row) => {
    if (row.status === 'pending') {
      return <span className={`${styles.reviewerCallStatus} ${styles.reviewerCallPending}`}>queued…</span>;
    }
    if (row.status === 'running') {
      return <span className={`${styles.reviewerCallStatus} ${styles.reviewerCallRunning}`}>reviewing…</span>;
    }
    if (row.status === 'failed') {
      return <span className={`${styles.reviewerCallStatus} ${styles.reviewerCallFailed}`}>❌ technical failure</span>;
    }
    // completed
    if (row.passed && row.issue_count === 0) {
      return <span className={`${styles.reviewerCallStatus} ${styles.reviewerCallClean}`}>✅ passed</span>;
    }
    return <span className={`${styles.reviewerCallStatus} ${styles.reviewerCallIssues}`}>⚠️ {row.issue_count} {row.issue_count === 1 ? 'issue' : 'issues'}</span>;
  };

  const renderLeading = (row) => {
    // Cover / page / the_end → render a tiny thumbnail of the actual image.
    // Story text / cross_page → no icon at all (per design).
    let slot = null;
    if (row.call_kind === 'cover') slot = 0;
    else if (row.call_kind === 'page' && row.page_number != null) slot = row.page_number;
    else if (row.call_kind === 'the_end') slot = pageCount + 1;
    else return null;

    const url = imageUrlByPageNumber[slot];
    if (url) {
      return (
        <img
          src={url}
          alt={row.call_label}
          className={styles.reviewerCallThumb}
          loading="lazy"
        />
      );
    }
    // Image slot exists for this kind but the URL isn't available — leave a
    // neutral placeholder so the row stays aligned with siblings that do have
    // thumbnails.
    return <span className={`${styles.reviewerCallThumb} ${styles.reviewerCallThumbMissing}`} aria-hidden="true" />;
  };

  return (
    <div className={styles.reviewerCallList}>
      <div className={styles.reviewerCallListHeader}>
        <span className={styles.detailLabel}>Reviewer subcalls</span>
        <span className={styles.reviewerCallProgress}>{completedCount} / {total} complete</span>
      </div>
      <div className={styles.reviewerCallProgressBarOuter}>
        <div
          className={styles.reviewerCallProgressBarInner}
          style={{ width: total > 0 ? `${(completedCount / total) * 100}%` : '0%' }}
        />
      </div>
      <div className={styles.reviewerCallRows}>
        {(() => {
          let imageGroupHeaderEmitted = false;
          return rows.map(row => {
            const leading = renderLeading(row);
            const hasDetails = (row.issues && row.issues.length > 0) || row.error;
            const isExpanded = expandedCallId === row.call_id;
            const isImageKind = IMAGE_KINDS.has(row.call_kind);
            const inlineDesc = REVIEWER_ROW_DESCRIPTIONS[row.call_kind];

            // Emit a one-time grouped description above the FIRST image-kind
            // row so the user gets context for what the cover/page/the_end
            // reviewers are checking, without repeating it per row.
            let groupHeader = null;
            if (isImageKind && !imageGroupHeaderEmitted) {
              imageGroupHeaderEmitted = true;
              groupHeader = (
                <div className={styles.reviewerCallGroupHeader} key="__image_group_header">
                  {REVIEWER_GROUP_DESCRIPTION_IMAGES}
                </div>
              );
            }

            return (
              <Fragment key={row.call_id}>
                {groupHeader}
                <div className={styles.reviewerCallRow}>
                  <div
                    className={hasDetails ? styles.reviewerCallRowHeaderClickable : styles.reviewerCallRowHeader}
                    onClick={hasDetails ? () => setExpandedCallId(isExpanded ? null : row.call_id) : undefined}
                  >
                    <div className={styles.reviewerCallRowHeaderInner}>
                      {leading}
                      <span className={styles.reviewerCallLabel}>{row.call_label}</span>
                      {renderStatus(row)}
                      {hasDetails && (
                        <span className={styles.reviewerCallExpandHint}>{isExpanded ? '▲' : '▼'}</span>
                      )}
                    </div>
                    {inlineDesc && (
                      <div className={styles.reviewerCallRowDescription}>{inlineDesc}</div>
                    )}
                  </div>
                  {isExpanded && row.issues && row.issues.length > 0 && (
                    <div className={styles.reviewerCallDetails}>
                      {row.issues.map((issue, i) => (
                        <div key={i} className={styles.issueRow}>
                          <span className={styles.issueCategory}>{issue.severity}</span>
                          <span className={styles.issueCategory}>{issue.category}</span>
                          <span>{issue.description}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {isExpanded && row.error && (
                    <div className={styles.reviewerCallDetails}>
                      <div className={styles.issueRow}>
                        <span>{row.error}</span>
                      </div>
                    </div>
                  )}
                </div>
              </Fragment>
            );
          });
        })()}
      </div>
    </div>
  );
}

function PageContentBlock({ pages }) {
  if (!pages?.length) return null;
  return (
    <div className={styles.pagesBlock}>
      <div className={styles.detailLabel}>Pages written ({pages.length})</div>
      <div className={styles.pagesList}>
        {pages.map(page => (
          <div key={page.page_number} className={styles.pageCard}>
            <div className={styles.pageCardHeader}>
              <span className={styles.pageNum}>Page {page.page_number}</span>
              <span className={styles.pageTone}>{page.emotional_tone}</span>
            </div>
            <p className={styles.pageText}>{page.text}</p>
            <div className={styles.pageImagePromptLabel}>Image prompt:</div>
            <p className={styles.pageImagePrompt}>{page.image_prompt}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Lightbox ────────────────────────────────────────────────────────────── */

function Lightbox({ images, currentIndex, onClose, onPrev, onNext }) {
  if (!images?.length) return null;
  const { src, label } = images[currentIndex];
  const hasPrev = currentIndex > 0;
  const hasNext = currentIndex < images.length - 1;

  return (
    <div className={styles.lightboxBackdrop} onClick={onClose}>
      <div className={styles.lightboxContent} onClick={e => e.stopPropagation()}>
        <button className={styles.lightboxClose} onClick={onClose} title="Close">✕</button>
        {hasPrev && (
          <button className={`${styles.lightboxNav} ${styles.lightboxNavPrev}`} onClick={onPrev} title="Previous image">‹</button>
        )}
        <img src={src} alt={label} className={styles.lightboxImage} />
        {hasNext && (
          <button className={`${styles.lightboxNav} ${styles.lightboxNavNext}`} onClick={onNext} title="Next image">›</button>
        )}
        {label && <div className={styles.lightboxLabel}>{label} ({currentIndex + 1}/{images.length})</div>}
      </div>
    </div>
  );
}

function ImageGrid({ imageEvents, totalPages, batchEvt }) {
  const [lightboxIndex, setLightboxIndex] = useState(null);

  const isPartial = batchEvt?.data?.partial === true;
  const affectedSlots = isPartial
    ? new Set(
        (batchEvt?.data?.affected_slots ?? [])
          .filter(n => typeof n === 'number')
      )
    : null;
  const revisionRound = batchEvt?.data?.revision_round;

  const imageMap = useMemo(() => {
    const map = {};
    for (const ev of imageEvents) {
      const pn = ev.data?.page_number;
      if (pn != null) {
        const priority = { image_queued: 0, image_started: 1, image_completed: 2, image_failed: 2 };
        const cur = map[pn];
        if (!cur || (priority[ev.detail_type] ?? -1) >= (priority[cur.detail_type] ?? -1)) {
          map[pn] = ev;
        }
      }
    }
    return map;
  }, [imageEvents]);

  if (!imageEvents.length && !isPartial) return null;

  const count = totalPages
    || batchEvt?.data?.total_pages
    || Math.max(...imageEvents.map(e => e.data?.total_pages ?? 0), 0);

  let slots;
  if (isPartial) {
    // Partial revision: only render the slots that are actually being
    // regenerated. Prefer the batch event's `affected_slots` (authoritative,
    // present at round-start) and fall back to event-derived slots if the
    // backend ever omits it.
    if (affectedSlots && affectedSlots.size > 0) {
      slots = [...affectedSlots].sort((a, b) => a - b);
    } else {
      slots = [...new Set(imageEvents.map(e => e.data?.page_number).filter(n => n != null))]
        .sort((a, b) => a - b);
    }
  } else if (count > 0) {
    // Full pass: cover (0), story pages (1..count), "The End" (count+1)
    slots = [0, ...Array.from({ length: count }, (_, i) => i + 1), count + 1];
  } else {
    slots = [...new Set(imageEvents.map(e => e.data?.page_number).filter(n => n != null))]
      .sort((a, b) => a - b);
  }

  const slotLabel = (n) => {
    if (n === 0) return 'Cover';
    if (count > 0 && n === count + 1) return 'The End';
    return `Page ${n}`;
  };

  const completedImages = useMemo(() =>
    slots
      .filter(pn => imageMap[pn]?.detail_type === 'image_completed' && imageMap[pn]?.data?.image_url)
      .map(pn => ({ src: imageMap[pn].data.image_url, label: imageMap[pn].data?.label || slotLabel(pn), pageNum: pn })),
    [imageMap, slots]
  );

  const completedCount = Object.values(imageMap).filter(e => e.detail_type === 'image_completed').length;
  const activeCount = Object.values(imageMap).filter(e => e.detail_type === 'image_started').length;

  const headerLabel = isPartial
    ? `Partial revision${revisionRound != null ? ` (round ${revisionRound})` : ''} — ${completedCount}/${slots.length} regenerated${activeCount > 0 ? `, ${activeCount} in progress` : ''}`
    : `Illustrations (${completedCount}/${slots.length} done${activeCount > 0 ? `, ${activeCount} generating` : ''})`;

  return (
    <>
      <div className={styles.imageGridBlock}>
        <div className={styles.detailLabel}>{headerLabel}</div>
        <div className={styles.imageGrid}>
          {slots.map(pageNum => {
            const ev = imageMap[pageNum];
            const dt = ev?.detail_type;
            const label = ev?.data?.label || slotLabel(pageNum);
            const isClickable = dt === 'image_completed' && ev.data?.image_url;

            return (
              <div
                key={pageNum}
                className={`${styles.imageSlot} ${
                  dt === 'image_completed' ? styles.imageSlotDone :
                  dt === 'image_failed'   ? styles.imageSlotFail :
                  dt === 'image_started'  ? styles.imageSlotLoading :
                  dt === 'image_queued'   ? styles.imageSlotQueued : ''
                } ${isClickable ? styles.imageSlotClickable : ''}`}
                onClick={isClickable ? () => {
                  const idx = completedImages.findIndex(img => img.pageNum === pageNum);
                  if (idx !== -1) setLightboxIndex(idx);
                } : undefined}
                title={isClickable ? `View ${label} full size` : undefined}
              >
                {dt === 'image_completed' && ev.data?.image_url
                  ? <img src={ev.data.image_url} alt={label} className={styles.imageThumbnail} />
                  : dt === 'image_failed'
                  ? <div className={styles.imageSlotError}>✕</div>
                  : dt === 'image_started'
                  ? <div className={styles.imageSlotSpinner}><span className="spinner spinner--dark" /></div>
                  : dt === 'image_queued'
                  ? <div className={styles.imageSlotQueuedIcon}>⏳</div>
                  : <div className={styles.imageSlotPending} />
                }
                <div className={styles.imageSlotLabel}>{slotLabel(pageNum)}</div>
              </div>
            );
          })}
        </div>
      </div>

      {lightboxIndex != null && completedImages.length > 0 && (
        <Lightbox
          images={completedImages}
          currentIndex={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          onPrev={() => setLightboxIndex(i => Math.max(0, i - 1))}
          onNext={() => setLightboxIndex(i => Math.min(completedImages.length - 1, i + 1))}
        />
      )}
    </>
  );
}

function StepDetailPanel({ stepId, details }) {
  const stepEvts = details.filter(d => d.executor_id === stepId);
  if (!stepEvts.length) return null;

  // Reviewer thumbnails: pull the latest completed image_url per page_number
  // out of the FULL details stream (image events are emitted by art_director,
  // not story_reviewer, so they aren't in stepEvts above).
  const imageUrlByPageNumber = {};
  if (stepId === 'story_reviewer') {
    for (const ev of details) {
      if (ev.detail_type === 'image_completed' && ev.data?.page_number != null && ev.data?.image_url) {
        imageUrlByPageNumber[ev.data.page_number] = ev.data.image_url;
      }
    }
  }

  // Group events into rounds.
  // orchestrator rounds pivot on executor_started / revision_started.
  // art_director rounds pivot on images_batch_started.
  // All other agents pivot on prompt_sent.
  const isPivot = (ev) => {
    if (stepId === 'art_director') return ev.detail_type === 'images_batch_started';
    if (stepId === 'orchestrator') return ev.detail_type === 'executor_started' || ev.detail_type === 'revision_started';
    return ev.detail_type === 'prompt_sent';
  };

  const PIVOT = stepId === 'art_director' ? 'images_batch_started' : 'prompt_sent';

  const rounds = [];
  let current = [];
  for (const ev of stepEvts) {
    if (isPivot(ev) && current.length > 0) {
      rounds.push(current);
      current = [];
    }
    current.push(ev);
  }
  if (current.length > 0) rounds.push(current);

  return (
    <div className={styles.stepDetail}>
      {rounds.map((round, roundIdx) => {
        const promptEvt          = round.find(d => d.detail_type === 'prompt_sent');
        const responseEvt        = round.find(d => d.detail_type === 'response_received');
        const autoApprovedEvt    = round.find(d => d.detail_type === 'auto_approved');
        const executorStartedEvt = round.find(d => d.detail_type === 'executor_started');
        const revisionStartedEvt = round.find(d => d.detail_type === 'revision_started');
        const wikiFetchedEvt     = round.find(d => d.detail_type === 'wikipedia_fetched');
        const wikiNotFoundEvt    = round.find(d => d.detail_type === 'wikipedia_not_found');

        // Deduplicate pages by page_number — last event wins
        const pageMap = {};
        for (const ev of round.filter(d => d.detail_type === 'page_content')) {
          if (ev.data?.page_number != null) pageMap[ev.data.page_number] = ev.data;
        }
        const pageEvts = Object.values(pageMap).sort((a, b) => a.page_number - b.page_number);

        const imageEvts = round.filter(d =>
          d.detail_type === 'image_queued'    ||
          d.detail_type === 'image_started'   ||
          d.detail_type === 'image_completed' ||
          d.detail_type === 'image_failed'
        );
        const batchEvt = round.find(d => d.detail_type === 'images_batch_started');
        const reviewerCallEvts = round.filter(d =>
          d.detail_type === 'review_call_started'   ||
          d.detail_type === 'review_call_completed' ||
          d.detail_type === 'review_call_failed'
        );
        const totalPages = round.find(d => d.data?.total_pages)?.data?.total_pages ?? pageEvts.length ?? 0;

        return (
          <div key={roundIdx} className={rounds.length > 1 ? styles.revisionRound : undefined}>
            {rounds.length > 1 && (
              <div className={styles.roundLabel}>
                {roundIdx === 0 ? '— Initial pass' : `🔄 Revision ${roundIdx}`}
              </div>
            )}
            {autoApprovedEvt     && <AutoApprovedBlock />}
            {executorStartedEvt  && <ExecutorStartedBlock data={executorStartedEvt.data} />}
            {wikiFetchedEvt      && <WikipediaFetchedBlock data={wikiFetchedEvt.data} />}
            {wikiNotFoundEvt     && <WikipediaNotFoundBlock data={wikiNotFoundEvt.data} />}
            {revisionStartedEvt  && <RevisionStartedBlock data={revisionStartedEvt.data} />}
            {promptEvt   && <PromptBlock text={promptEvt.data?.prompt} />}
            {pageEvts.length  > 0 && <PageContentBlock pages={pageEvts} />}
            {imageEvts.length > 0 && <ImageGrid imageEvents={imageEvts} totalPages={totalPages} batchEvt={batchEvt} />}
            {stepId === 'story_reviewer' && promptEvt?.data?.calls && (
              <ReviewerCallList
                promptEvt={promptEvt}
                callEvts={reviewerCallEvts}
                imageUrlByPageNumber={imageUrlByPageNumber}
              />
            )}
            {responseEvt && <ResponseBlock data={responseEvt.data} executorId={stepId} />}
          </div>
        );
      })}
    </div>
  );
}

/* ─── Main component ──────────────────────────────────────────────────────── */

export default function ProgressTracker({
  progress,
  details = [],
  error,
  mode = 'full',
  isCollapsed = false,
  onToggle,
  bonusAgents = { lookAndFind: true, characterGlossary: true },
  reviewNotes,
}) {
  const revisionEvents = progress.filter(p => p.executor_id === 'revision');
  const isSidebar = mode === 'sidebar';
  const workflowSteps = useMemo(() => buildWorkflowSteps(bonusAgents), [bonusAgents]);

  return (
    <div className={`${styles.container} ${isSidebar ? styles.containerSidebar : ''}`}>

      {/* Reopen tab is handled externally (App.jsx sidebar-reopener button) */}

      {/* Panel body — hidden when sidebar is collapsed */}
      {(!isSidebar || !isCollapsed) && (
        <div className={styles.panelContent}>

          {/* Header */}
          {!isSidebar ? (
            <>
              <h2 className={styles.title}>Writing Your Story…</h2>
              <p className={styles.subtitle}>
                Our AI agents are crafting a magical story just for you.
                <br />This may take a minute or two — good things take time!
              </p>
            </>
          ) : (
            <div className={styles.sidebarHeader}>
              <span className={styles.sidebarTitle}>Generation Log</span>
              <button className={styles.collapseBtn} onClick={onToggle} title="Hide log">✕</button>
            </div>
          )}

          {/* Workflow steps */}
          <div className={styles.workflow}>
            {workflowSteps.map((step, idx) => {
              const status  = resolveStepStatus(step.id, progress, details);
              const progEvt = progress.filter(p => p.executor_id === step.id).at(-1);
              const isAutoApproved = step.id === 'story_reviewer' &&
                details.some(d => d.executor_id === 'story_reviewer' && d.detail_type === 'auto_approved');
              const message = isAutoApproved
                ? 'Auto-approved — reviewer skipped'
                : progEvt?.message || step.hint;
              const isLast  = idx === workflowSteps.length - 1;

              return (
                <div key={step.id} className={`${styles.step} ${styles[status]}`}>
                  <div className={styles.iconCol}>
                    <div className={styles.icon}>{step.icon}</div>
                    {!isLast && (
                      <div className={`${styles.connector} ${status === 'completed' ? styles.connectorDone : ''}`} />
                    )}
                  </div>

                  <div className={styles.content}>
                    <div className={styles.stepHeader}>
                      <span className={styles.stepLabel}>{step.label}</span>
                      {status === 'active'    && <span className="spinner spinner--dark" />}
                      {status === 'completed' && <span className={styles.checkmark}>✔</span>}
                    </div>

                    <div className={styles.stepMessage}>
                      {status === 'active' || status === 'completed'
                        ? message
                        : <span style={{ opacity: 0.45 }}>{step.hint}</span>}
                    </div>

                    <StepDetailPanel stepId={step.id} details={details} />

                    {step.id === 'story_reviewer' && revisionEvents.map((rev, i) => (
                      <div key={i} className={styles.revisionBadge}>🔄 {rev.message}</div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Reviewer notes — shown in sidebar mode after all steps */}
          {isSidebar && reviewNotes && reviewNotes !== 'Story approved with no issues.' && (
            <div className={styles.reviewBanner}>
              {reviewNotes}
            </div>
          )}

          {error && (
            <div className={styles.errorBox}>
              <p>⚠️ Something went wrong</p>
              <p>{error}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
