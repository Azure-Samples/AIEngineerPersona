import { useMemo, useState } from 'react';
import styles from './ProgressTracker.module.css';

/* ─── Static step definitions ─────────────────────────────────────────────── */

const WORKFLOW_STEPS = [
  { id: 'orchestrator',    icon: '📋', label: 'Orchestrator',    hint: 'Planning the story outline...' },
  { id: 'story_architect', icon: '✍️',  label: 'Story Architect', hint: 'Writing the story pages...' },
  { id: 'art_director',    icon: '🎨', label: 'Art Director',    hint: 'Generating illustrations...' },
  { id: 'story_reviewer',  icon: '🔍', label: 'Story Reviewer',  hint: 'Reviewing for quality...' },
  { id: 'decision',        icon: '⚖️',  label: 'Decision',       hint: 'Finalising the story...' },
];

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
    const activeTypes    = new Set(['executor_started', 'revision_started', 'prompt_sent', 'page_content', 'image_started', 'image_queued', 'images_batch_started']);
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
      <div className={styles.detailLabel}>🗨 Prompt sent</div>
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
      <div className={styles.detailLabel}>⚡ Auto-approved — story reviewer skipped</div>
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
  return null;
}

function ExecutorStartedBlock({ data }) {
  if (!data) return null;
  return (
    <div className={styles.responseBlock}>
      <div className={styles.detailLabel}>📥 Story request received</div>
      <div className={styles.responseRow}><span className={styles.responseKey}>Hero</span><span>{data.main_character}</span></div>
      {data.supporting_characters?.length > 0 && (
        <div className={styles.responseRow}><span className={styles.responseKey}>Also</span><span>{data.supporting_characters.join(', ')}</span></div>
      )}
      <div className={styles.responseRow}><span className={styles.responseKey}>Setting</span><span>{data.setting}</span></div>
      <div className={styles.responseRow}><span className={styles.responseKey}>Moral</span><span>{data.moral}</span></div>
      <div className={styles.responseRow}><span className={styles.responseKey}>Problem</span><span>{data.main_problem}</span></div>
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

function PageContentBlock({ pages }) {
  if (!pages?.length) return null;
  return (
    <div className={styles.pagesBlock}>
      <div className={styles.detailLabel}>📝 Pages written ({pages.length})</div>
      <div className={styles.pagesList}>
        {pages.map(page => (
          <div key={page.page_number} className={styles.pageCard}>
            <div className={styles.pageCardHeader}>
              <span className={styles.pageNum}>Page {page.page_number}</span>
              <span className={styles.pageTone}>{page.emotional_tone}</span>
            </div>
            <p className={styles.pageText}>{page.text}</p>
            <div className={styles.pageImagePromptLabel}>🖼 Image prompt:</div>
            <p className={styles.pageImagePrompt}>{page.image_prompt}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Lightbox ────────────────────────────────────────────────────────────── */

function Lightbox({ src, label, onClose }) {
  if (!src) return null;
  return (
    <div className={styles.lightboxBackdrop} onClick={onClose}>
      <div className={styles.lightboxContent} onClick={e => e.stopPropagation()}>
        <button className={styles.lightboxClose} onClick={onClose} title="Close">✕</button>
        <img src={src} alt={label} className={styles.lightboxImage} />
        {label && <div className={styles.lightboxLabel}>{label}</div>}
      </div>
    </div>
  );
}

function ImageGrid({ imageEvents, totalPages }) {
  const [lightbox, setLightbox] = useState(null); // { src, label }

  const imageMap = useMemo(() => {
    const map = {};
    for (const ev of imageEvents) {
      const pn = ev.data?.page_number;
      if (pn != null) {
        // Later events always win, preserving completed over started over queued
        const priority = { image_queued: 0, image_started: 1, image_completed: 2, image_failed: 2 };
        const cur = map[pn];
        if (!cur || (priority[ev.detail_type] ?? -1) >= (priority[cur.detail_type] ?? -1)) {
          map[pn] = ev;
        }
      }
    }
    return map;
  }, [imageEvents]);

  if (!imageEvents.length) return null;

  const count = totalPages || Math.max(...imageEvents.map(e => e.data?.total_pages ?? 0), 0);

  // Slots: cover (0), story pages (1..count), "The End" (count+1)
  const slots = count > 0
    ? [0, ...Array.from({ length: count }, (_, i) => i + 1), count + 1]
    : [...new Set(imageEvents.map(e => e.data?.page_number).filter(n => n != null))].sort((a, b) => a - b);

  const slotLabel = (n) => {
    if (n === 0) return 'Cover';
    if (n === count + 1) return 'The End';
    return `Page ${n}`;
  };

  const completedCount = Object.values(imageMap).filter(e => e.detail_type === 'image_completed').length;
  const activeCount = Object.values(imageMap).filter(e => e.detail_type === 'image_started').length;

  return (
    <>
      <div className={styles.imageGridBlock}>
        <div className={styles.detailLabel}>
          🖼 Illustrations ({completedCount}/{slots.length} done{activeCount > 0 ? `, ${activeCount} generating` : ''})
        </div>
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
                onClick={isClickable ? () => setLightbox({ src: ev.data.image_url, label }) : undefined}
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

      {lightbox && (
        <Lightbox src={lightbox.src} label={lightbox.label} onClose={() => setLightbox(null)} />
      )}
    </>
  );
}

function StepDetailPanel({ stepId, details }) {
  const stepEvts = details.filter(d => d.executor_id === stepId);
  if (!stepEvts.length) return null;

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
        const promptEvt         = round.find(d => d.detail_type === 'prompt_sent');
        const responseEvt        = round.find(d => d.detail_type === 'response_received');
        const autoApprovedEvt    = round.find(d => d.detail_type === 'auto_approved');
        const executorStartedEvt = round.find(d => d.detail_type === 'executor_started');
        const revisionStartedEvt = round.find(d => d.detail_type === 'revision_started');

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
        const totalPages = round.find(d => d.data?.total_pages)?.data?.total_pages ?? pageEvts.length ?? 0;

        return (
          <div key={roundIdx} className={rounds.length > 1 ? styles.revisionRound : undefined}>
            {rounds.length > 1 && (
              <div className={styles.roundLabel}>
                {roundIdx === 0 ? '— Initial pass' : `🔄 Revision ${roundIdx}`}
              </div>
            )}
            {autoApprovedEvt  && <AutoApprovedBlock />}
            {executorStartedEvt && <ExecutorStartedBlock data={executorStartedEvt.data} />}
            {revisionStartedEvt && <RevisionStartedBlock data={revisionStartedEvt.data} />}
            {promptEvt   && <PromptBlock text={promptEvt.data?.prompt} />}
            {pageEvts.length  > 0 && <PageContentBlock pages={pageEvts} />}
            {imageEvts.length > 0 && <ImageGrid imageEvents={imageEvts} totalPages={totalPages} />}
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
}) {
  const revisionEvents = progress.filter(p => p.executor_id === 'revision');
  const isSidebar = mode === 'sidebar';

  return (
    <div className={`${styles.container} ${isSidebar ? styles.containerSidebar : ''}`}>

      {/* Reopen tab is handled externally (App.jsx sidebar-reopener button) */}

      {/* Panel body — hidden when sidebar is collapsed */}
      {(!isSidebar || !isCollapsed) && (
        <div className={styles.panelContent}>

          {/* Header */}
          {!isSidebar ? (
            <>
              <h2 className={styles.title}>📖 Writing Your Story…</h2>
              <p className={styles.subtitle}>
                Our AI agents are crafting a magical story just for you.
                <br />This may take a minute or two — good things take time!
              </p>
            </>
          ) : (
            <div className={styles.sidebarHeader}>
              <span className={styles.sidebarTitle}>⚙ Generation Log</span>
              <button className={styles.collapseBtn} onClick={onToggle} title="Hide log">✕</button>
            </div>
          )}

          {/* Workflow steps */}
          <div className={styles.workflow}>
            {WORKFLOW_STEPS.map((step, idx) => {
              const status  = resolveStepStatus(step.id, progress, details);
              const progEvt = progress.filter(p => p.executor_id === step.id).at(-1);
              const isAutoApproved = step.id === 'story_reviewer' &&
                details.some(d => d.executor_id === 'story_reviewer' && d.detail_type === 'auto_approved');
              const message = isAutoApproved
                ? 'Auto-approved — reviewer skipped'
                : progEvt?.message || step.hint;
              const isLast  = idx === WORKFLOW_STEPS.length - 1;

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
