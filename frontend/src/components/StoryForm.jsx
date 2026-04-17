import { useState } from 'react';
import styles from './StoryForm.module.css';

const DEFAULT_FORM = {
  main_character:       'Thomas the Turtle',
  supporting_characters: ['Oliver the Wise Owl', 'Benny the Bunny'],
  setting:              'A magical forest',
  moral:                "True courage means helping others even when you're scared",
  main_problem:         "A mysterious fog has covered the forest and Thomas' friend, Benny the Bunny, is lost inside it. Thomas must find Benny and bring him back safely.",
  additional_details:   '',
};

export default function StoryForm({ onSubmit, isGenerating }) {
  const [form, setForm] = useState(DEFAULT_FORM);

  // ─── Field handlers ────────────────────────────────────────────────────────

  function handleField(field) {
    return (e) => setForm(prev => ({ ...prev, [field]: e.target.value }));
  }

  function handleCharacterChange(index, value) {
    setForm(prev => {
      const updated = [...prev.supporting_characters];
      updated[index] = value;
      return { ...prev, supporting_characters: updated };
    });
  }

  function addCharacter() {
    setForm(prev => ({
      ...prev,
      supporting_characters: [...prev.supporting_characters, ''],
    }));
  }

  function removeCharacter(index) {
    setForm(prev => ({
      ...prev,
      supporting_characters: prev.supporting_characters.filter((_, i) => i !== index),
    }));
  }

  // ─── Submit ────────────────────────────────────────────────────────────────

  function handleSubmit(e) {
    e.preventDefault();
    // Filter out empty supporting character names
    const payload = {
      ...form,
      supporting_characters: form.supporting_characters.filter(s => s.trim() !== ''),
    };
    onSubmit(payload);
  }

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div className={styles.container}>
      <h2 className={styles.title}>✨ Create a Children's Story</h2>
      <p className={styles.subtitle}>
        Fill in the details below and let the AI agents craft a magical illustrated story!
      </p>

      <form onSubmit={handleSubmit}>

        {/* ── Main characters section ───────────────────────────────── */}
        <div className={styles.sectionTitle}>🐰 Characters</div>

        <div className={styles.field}>
          <label className={styles.label}>
            Main Character Name <span className={styles.required}>*</span>
          </label>
          <input
            className={styles.input}
            type="text"
            placeholder="e.g. Benny the Brave Bunny"
            value={form.main_character}
            onChange={handleField('main_character')}
            required
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label}>Supporting Characters</label>
          <div className={styles.characterList}>
            {form.supporting_characters.map((char, i) => (
              <div key={i} className={styles.characterRow}>
                <input
                  className={styles.input}
                  type="text"
                  placeholder={i === 0 ? 'e.g. Rosie the Fox' : 'e.g. Oliver the Owl'}
                  value={char}
                  onChange={(e) => handleCharacterChange(i, e.target.value)}
                />
                <button
                  type="button"
                  className={styles.btnRemove}
                  onClick={() => removeCharacter(i)}
                  aria-label="Remove character"
                >
                  ×
                </button>
              </div>
            ))}
            <button type="button" className={styles.btnAdd} onClick={addCharacter}>
              + Add Character
            </button>
          </div>
        </div>

        <hr className={styles.divider} />

        {/* ── World & story section ─────────────────────────────────── */}
        <div className={styles.sectionTitle}>🌿 The World & Story</div>

        <div className={styles.field}>
          <label className={styles.label}>
            Setting <span className={styles.required}>*</span>
          </label>
          <input
            className={styles.input}
            type="text"
            placeholder="e.g. A magical forest with talking trees and glowing fireflies"
            value={form.setting}
            onChange={handleField('setting')}
            required
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label}>
            Moral of the Story <span className={styles.required}>*</span>
          </label>
          <input
            className={styles.input}
            type="text"
            placeholder="e.g. True courage means helping others even when you're scared"
            value={form.moral}
            onChange={handleField('moral')}
            required
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label}>
            Main Problem / Central Challenge <span className={styles.required}>*</span>
          </label>
          <textarea
            className={styles.textarea}
            placeholder="e.g. A mysterious fog has covered the forest, and the animals can't find their way home"
            value={form.main_problem}
            onChange={handleField('main_problem')}
            required
          />
        </div>

        <hr className={styles.divider} />

        {/* ── Additional details ────────────────────────────────────── */}
        <div className={styles.sectionTitle}>✏️ Additional Details (optional)</div>

        <div className={styles.field}>
          <label className={styles.label}>Extra Details, Scenes, or Themes</label>
          <textarea
            className={styles.textarea}
            placeholder="e.g. Include a scene where the characters work together to solve a puzzle"
            value={form.additional_details}
            onChange={handleField('additional_details')}
          />
        </div>

        {/* ── Submit ────────────────────────────────────────────────── */}
        <div className={styles.submitRow}>
          <button
            type="submit"
            className="btn-primary"
            disabled={isGenerating}
          >
            {isGenerating ? (
              <>
                <span className="spinner" />
                Creating your story…
              </>
            ) : (
              '🪄 Create My Story!'
            )}
          </button>
        </div>

      </form>
    </div>
  );
}
