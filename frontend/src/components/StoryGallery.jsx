import { useState, useEffect } from 'react';
import styles from './StoryGallery.module.css';

export default function StoryGallery({ onLoadStory }) {
  const [stories, setStories] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/demo-stories')
      .then(r => r.ok ? r.json() : [])
      .then(list => setStories(list || []))
      .catch(() => setStories([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className={styles.container}>
        <p className={styles.empty}>Loading saved stories…</p>
      </div>
    );
  }

  if (stories.length === 0) {
    return (
      <div className={styles.container}>
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>No saved stories yet</p>
          <p className={styles.emptyHint}>
            Create a story and click "Save Story" to add it here.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.grid}>
        {stories.map(story => (
          <button
            key={story.id}
            type="button"
            className={styles.card}
            onClick={() => onLoadStory(story.id)}
          >
            {story.cover_image_url && (
              <img
                src={story.cover_image_url}
                alt={story.title}
                className={styles.cover}
              />
            )}
            <div className={styles.cardBody}>
              <div className={styles.title}>{story.title}</div>
              {story.description && (
                <div className={styles.description}>{story.description}</div>
              )}
              {story.moral && (
                <div className={styles.moral}>💡 {story.moral}</div>
              )}
              {story.models_used?.length > 0 && (
                <div className={styles.models}>
                  {story.models_used.map(m => (
                    <span key={m} className={styles.modelChip}>{m}</span>
                  ))}
                </div>
              )}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
