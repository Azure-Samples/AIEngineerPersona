import { useEffect, useState } from 'react';
import styles from './StoryForm.module.css';
import watercolorSrc   from '../assets/sample_art/watercolor.png';
import comicBookSrc    from '../assets/sample_art/comic_book.png';
import crayonSrc       from '../assets/sample_art/crayon.png';
import paperCollageSrc from '../assets/sample_art/paper_collage.png';

const DEFAULT_FORM = {
  main_character:             'Thomas the Turtle',
  supporting_characters:      ['Oliver the Wise Owl', 'Benny the Bunny'],
  setting:                    'A magical forest',
  moral:                      "True courage means helping others even when you're scared",
  main_problem:               "A mysterious fog has covered the forest and Thomas' friend, Benny the Bunny, is lost inside it. Thomas must find Benny and bring him back safely.",
  art_style:                  'watercolor',
  additional_details:         '',
  enable_story_reviewer:      true,
};

const ART_STYLES = [
  {
    id:    'watercolor',
    label: 'Watercolor',
    desc:  'Soft, painted look with warm washes of color',
    sample: watercolorSrc,
  },
  {
    id:    'comic_book',
    label: 'Comic Book',
    desc:  'Bold ink outlines and bright, saturated colors',
    sample: comicBookSrc,
  },
  {
    id:    'crayon',
    label: 'Crayon Sketch',
    desc:  'Hand-drawn crayon strokes with a charming, childlike feel',
    sample: crayonSrc,
  },
  {
    id:    'paper_collage',
    label: 'Paper Collage',
    desc:  'Eric Carle-inspired cut-paper textures and bold shapes',
    sample: paperCollageSrc,
  },
];

export default function StoryForm({ onSubmit, isGenerating }) {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [isSuggesting, setIsSuggesting] = useState(false);
  const [suggestError, setSuggestError] = useState(null);
  const [stylePreview, setStylePreview] = useState(null); // {src, label} | null

  // Close art-style preview lightbox on Escape.
  useEffect(() => {
    if (!stylePreview) return;
    const onKey = (e) => { if (e.key === 'Escape') setStylePreview(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [stylePreview]);

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

  // ─── Auto-fill ("Surprise Me") ─────────────────────────────────────────────

  async function handleSurpriseMe() {
    if (isSuggesting || isGenerating) return;
    setIsSuggesting(true);
    setSuggestError(null);
    try {
      const res = await fetch('/api/suggest-story', { method: 'POST' });
      if (!res.ok) {
        let msg = `Suggestion request failed (${res.status})`;
        try {
          const body = await res.json();
          if (body?.detail) msg = body.detail;
        } catch { /* ignore parse errors */ }
        throw new Error(msg);
      }
      const data = await res.json();
      setForm(prev => ({
        ...prev,
        main_character:        data.main_character        ?? prev.main_character,
        supporting_characters: Array.isArray(data.supporting_characters) && data.supporting_characters.length > 0
                                 ? data.supporting_characters
                                 : prev.supporting_characters,
        setting:               data.setting               ?? prev.setting,
        moral:                 data.moral                 ?? prev.moral,
        main_problem:          data.main_problem          ?? prev.main_problem,
        additional_details:    data.additional_details    ?? prev.additional_details,
      }));
    } catch (err) {
      setSuggestError(err?.message || 'Failed to fetch a suggestion. Please try again.');
    } finally {
      setIsSuggesting(false);
    }
  }

  // ─── Submit ────────────────────────────────────────────────────────────────

  function handleSubmit(e) {
    e.preventDefault();
    const payload = {
      ...form,
      supporting_characters: form.supporting_characters.filter(s => s.trim() !== ''),
    };
    onSubmit(payload);
  }

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div className={styles.container}>
      <p className={styles.subtitle}>
        Fill in the details below and let the AI agents craft a magical illustrated story!
      </p>

      <form onSubmit={handleSubmit}>

        {/* ── Surprise Me (auto-fill text fields with an LLM-generated seed) ── */}
        <div className={styles.surpriseRow}>
          <button
            type="button"
            className={styles.btnSurprise}
            onClick={handleSurpriseMe}
            disabled={isSuggesting || isGenerating}
            title="Generate a fresh, creative set of values for every text field below."
          >
            {isSuggesting ? (
              <>
                <span className="spinner" />
                Dreaming up a new story…
              </>
            ) : (
              <>Surprise Me — Auto-fill the Form</>
            )}
          </button>
          <p className={styles.surpriseHint}>
            Replaces the character, setting, moral, problem, and details fields with a brand-new idea.
          </p>
          {suggestError && (
            <p className={styles.surpriseError} role="alert">{suggestError}</p>
          )}
        </div>

        <hr className={styles.divider} />

        {/* ── Main characters section ───────────────────────────────── */}
        <div className={styles.sectionTitle}>Characters</div>

        <fieldset className={styles.fieldset}>

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

        </fieldset>

        <hr className={styles.divider} />

        {/* ── World & story section ─────────────────────────────────── */}
        <div className={styles.sectionTitle}>The World &amp; Story</div>

        <fieldset className={styles.fieldset}>

          <div className={styles.field}>
            <label className={styles.label}>
              Setting <span className={styles.required}>*</span>
            </label>
            <textarea
              className={styles.textarea}
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
            <textarea
              className={styles.textarea}
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

          {/* ── Art-style pill selector (single-select; affects all illustrations) ── */}
          <div className={styles.field}>
            <label className={styles.label}>Art Style</label>
            <div className={styles.artStylePills} role="radiogroup" aria-label="Artistic style for the illustrations">
              {ART_STYLES.map(style => {
                const selected = form.art_style === style.id;
                return (
                  <div key={style.id} className={styles.artStylePillWrapper}>
                    <button
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      className={`${styles.artStylePill} ${selected ? styles.artStylePillSelected : ''}`}
                      onClick={() => setForm(prev => ({ ...prev, art_style: style.id }))}
                    >
                      <span className={styles.artStylePillName}>{style.label}</span>
                      <span className={styles.artStylePillDesc}>{style.desc}</span>
                      <img
                        src={style.sample}
                        alt={`Example illustration in ${style.label} style`}
                        className={styles.artStylePillSample}
                        loading="lazy"
                      />
                    </button>
                    <button
                      type="button"
                      className={styles.artStylePillMagnifier}
                      onClick={(e) => {
                        e.stopPropagation();
                        setStylePreview({ src: style.sample, label: style.label });
                      }}
                      aria-label={`View larger ${style.label} example`}
                      title="View a larger example of this art style"
                    >
                      🔍
                    </button>
                  </div>
                );
              })}
            </div>
          </div>

        </fieldset>

        <hr className={styles.divider} />

        {/* ── Additional details ────────────────────────────────────── */}
        <div className={styles.sectionTitle}>Additional Details (optional)</div>

        <fieldset className={styles.fieldset}>
          <div className={styles.field}>
            <label className={styles.label}>Extra Details, Scenes, or Themes</label>
            <textarea
              className={styles.textarea}
              placeholder="e.g. Include a scene where the characters work together to solve a puzzle"
              value={form.additional_details}
              onChange={handleField('additional_details')}
            />
          </div>
        </fieldset>

        <hr className={styles.divider} />

        {/* ── Advanced Options ──────────────────────────────────────── */}
        <div className={styles.sectionTitle}>Advanced Options</div>

        <div className={styles.checkboxGroup}>
          <label className={styles.checkboxLabel}>
            <input
              type="checkbox"
              className={styles.checkboxInput}
              checked={form.enable_story_reviewer}
              onChange={e => setForm(prev => ({ ...prev, enable_story_reviewer: e.target.checked }))}
            />
            <span className={styles.checkboxText}>
              <strong>Enable Story Reviewer</strong>
              <span className={styles.checkboxHint}>Runs a quality review step with potential revision loops — produces higher quality but takes longer</span>
            </span>
          </label>
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
              'Create My Story'
            )}
          </button>
        </div>

      </form>

      {stylePreview && (
        <div
          className={styles.stylePreviewBackdrop}
          onClick={() => setStylePreview(null)}
          role="dialog"
          aria-modal="true"
          aria-label={`Larger example of ${stylePreview.label} art style`}
        >
          <div className={styles.stylePreviewContent} onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className={styles.stylePreviewClose}
              onClick={() => setStylePreview(null)}
              aria-label="Close preview"
              title="Close (Esc)"
            >
              ✕
            </button>
            <img
              src={stylePreview.src}
              alt={`Larger example of ${stylePreview.label} art style`}
              className={styles.stylePreviewImage}
            />
            <div className={styles.stylePreviewLabel}>{stylePreview.label}</div>
          </div>
        </div>
      )}
    </div>
  );
}
