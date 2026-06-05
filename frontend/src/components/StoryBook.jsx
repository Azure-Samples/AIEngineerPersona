import { useState } from 'react';
import styles from './StoryBook.module.css';
import StoryPage, { CoverPage, FinalPage, LookAndFindPage, CharacterGlossaryPage } from './StoryPage';

/**
 * StoryBook — An interactive page-by-page flipbook viewer.
 *
 * Page index layout:
 *   0           → CoverPage
 *   1 … n       → story pages (story.pages[0] … story.pages[n-1])
 *   n + 1       → FinalPage ("The End")
 *   n + 2 …     → bonus pages (Look & Find, Character Glossary) if present
 */
export default function StoryBook({ story, onReset, onSave }) {
  const total = story.pages?.length ?? 0;

  // Build the ordered list of bonus pages from story data
  const bonusPages = [];
  if (story.look_and_find)      bonusPages.push({ type: 'look_and_find',      label: '🔎 Look & Find',       data: story.look_and_find });
  if (story.character_glossary) bonusPages.push({ type: 'character_glossary', label: '📖 Meet the Characters', data: story.character_glossary });

  // pageIndex 0 = cover, 1..total = story pages, total+1 = final, total+2... = bonus
  const maxPage = total + 1 + bonusPages.length;
  const [pageIndex, setPageIndex] = useState(0);
  const [saveStatus, setSaveStatus] = useState(null); // null | 'saving' | 'saved' | 'error'

  function prev() { setPageIndex(i => Math.max(0, i - 1)); }
  function next() { setPageIndex(i => Math.min(maxPage, i + 1)); }
  function goTo(idx) { setPageIndex(idx); }

  const isFirst = pageIndex === 0;
  const isLast  = pageIndex === maxPage;

  // ─── Render current page content ───────────────────────────────────────

  function renderPage() {
    if (pageIndex === 0)          return <CoverPage story={story} />;
    if (pageIndex <= total)       return <StoryPage page={story.pages[pageIndex - 1]} totalPages={total} />;
    if (pageIndex === total + 1)  return <FinalPage story={story} />;
    const bonus = bonusPages[pageIndex - total - 2];
    if (!bonus) return null;
    if (bonus.type === 'look_and_find')      return <LookAndFindPage activity={bonus.data} />;
    if (bonus.type === 'character_glossary') return <CharacterGlossaryPage glossary={bonus.data} />;
    return null;
  }

  function pageLabel() {
    if (pageIndex === 0)         return 'Cover';
    if (pageIndex === total + 1) return 'The End';
    if (pageIndex > total + 1)   return bonusPages[pageIndex - total - 2]?.label ?? 'Bonus';
    return `Page ${pageIndex} of ${total}`;
  }

  function dotLabel(i) {
    if (i === 0)          return 'Cover';
    if (i <= total)       return `Page ${i}`;
    if (i === total + 1)  return 'The End';
    return bonusPages[i - total - 2]?.label ?? 'Bonus';
  }

  // ─── Dots — one per page including cover, story, final, and bonus ───────

  const dotCount = maxPage + 1;

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <h2 className={styles.title}>{story.title}</h2>
        <p className={styles.meta}>
          {total} pages &nbsp;·&nbsp;
          {story.revision_rounds === 0
            ? 'Approved on first draft!'
            : `${story.revision_rounds} revision round${story.revision_rounds > 1 ? 's' : ''}`}
          {bonusPages.length > 0 && ` · ${bonusPages.length} bonus page${bonusPages.length > 1 ? 's' : ''}`}
        </p>
      </div>

      {/* Book */}
      <div className={styles.book}>
        {renderPage()}

        {/* Navigation */}
        <div className={styles.nav}>
          <button
            className={styles.navBtn}
            onClick={prev}
            disabled={isFirst}
            aria-label="Previous page"
          >
            ‹
          </button>

          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
            <div className={styles.dots}>
              {Array.from({ length: dotCount }).map((_, i) => {
                const label = dotLabel(i);
                const isSpecial = i === 0 || i > total;
                const isStoryPage = i >= 1 && i <= total;
                return (
                  <button
                    key={i}
                    className={[
                      styles.dot,
                      i === pageIndex ? styles.active : '',
                      isSpecial ? styles.dotLabeled : '',
                      isStoryPage ? styles.dotNumbered : '',
                    ].join(' ')}
                    onClick={() => goTo(i)}
                    aria-label={label}
                    title={label}
                  >
                    {isSpecial && <span className={styles.dotLabelText}>{label}</span>}
                    {isStoryPage && <span className={styles.dotNumber}>{i}</span>}
                  </button>
                );
              })}
            </div>
            <span className={styles.pageCounter}>{pageLabel()}</span>
          </div>

          <button
            className={styles.navBtn}
            onClick={next}
            disabled={isLast}
            aria-label="Next page"
          >
            ›
          </button>
        </div>
      </div>

      {/* Actions */}
      <div className={styles.actions}>
        {onSave && (
          <button
            className="btn-secondary"
            onClick={async () => {
              setSaveStatus('saving');
              try {
                await onSave();
                setSaveStatus('saved');
                setTimeout(() => setSaveStatus(null), 3000);
              } catch {
                setSaveStatus('error');
                setTimeout(() => setSaveStatus(null), 3000);
              }
            }}
            disabled={saveStatus === 'saving'}
          >
            {saveStatus === 'saving' ? 'Saving…' :
             saveStatus === 'saved'  ? 'Saved' :
             saveStatus === 'error'  ? 'Save Failed' :
             'Save Story'}
          </button>
        )}
        <button className="btn-secondary" onClick={onReset}>
          Create Another Story
        </button>
      </div>
    </div>
  );
}

