import { useState } from 'react';
import styles from './StoryBook.module.css';
import StoryPage, { CoverPage, FinalPage } from './StoryPage';

/**
 * StoryBook — An interactive page-by-page flipbook viewer.
 *
 * Page index layout:
 *   0           → CoverPage
 *   1 … n       → story pages (story.pages[0] … story.pages[n-1])
 *   n + 1       → FinalPage (moral summary)
 */
export default function StoryBook({ story, onReset }) {
  const total = story.pages?.length ?? 0;
  // pageIndex 0 = cover, 1..total = story pages, total+1 = final
  const maxPage = total + 1;
  const [pageIndex, setPageIndex] = useState(0);

  function prev() {
    setPageIndex(i => Math.max(0, i - 1));
  }

  function next() {
    setPageIndex(i => Math.min(maxPage, i + 1));
  }

  function goTo(idx) {
    setPageIndex(idx);
  }

  const isFirst = pageIndex === 0;
  const isLast  = pageIndex === maxPage;

  // ─── Render current page content ───────────────────────────────────────

  function renderPage() {
    if (pageIndex === 0)        return <CoverPage story={story} />;
    if (pageIndex === maxPage)  return <FinalPage story={story} />;
    const storyPage = story.pages[pageIndex - 1];
    return <StoryPage page={storyPage} totalPages={total} />;
  }

  // ─── Dots — one per actual story page + cover + final ──────────────────

  const dotCount = maxPage + 1; // cover + all pages + final

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
        </p>
      </div>

      {story.review_notes && story.review_notes !== 'Story approved with no issues.' && (
        <div className={styles.reviewBanner}>
          📝 {story.review_notes}
        </div>
      )}

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
              {Array.from({ length: dotCount }).map((_, i) => (
                <button
                  key={i}
                  className={[styles.dot, i === pageIndex ? styles.active : ''].join(' ')}
                  onClick={() => goTo(i)}
                  aria-label={`Go to page ${i}`}
                />
              ))}
            </div>
            <span className={styles.pageCounter}>
              {pageIndex === 0
                ? 'Cover'
                : pageIndex === maxPage
                ? 'The End'
                : `Page ${pageIndex} of ${total}`}
            </span>
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
        <button className="btn-secondary" onClick={onReset}>
          ✨ Create Another Story
        </button>
      </div>
    </div>
  );
}
