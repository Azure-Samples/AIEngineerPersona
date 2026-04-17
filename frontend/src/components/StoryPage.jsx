import styles from './StoryPage.module.css';

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
        <p className={styles.storyText}>{page.text}</p>
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
