import { useState } from 'react';
import styles from './StoryForm.module.css';

const DEFAULT_FORM = {
  wikipedia_topic:            '',
  wikipedia_mode:             'influence',
  main_character:             'Thomas the Turtle',
  supporting_characters:      ['Oliver the Wise Owl', 'Benny the Bunny'],
  setting:                    'A magical forest',
  moral:                      "True courage means helping others even when you're scared",
  main_problem:               "A mysterious fog has covered the forest and Thomas' friend, Benny the Bunny, is lost inside it. Thomas must find Benny and bring him back safely.",
  additional_details:         '',
  include_look_and_find:      true,
  include_character_glossary: true,
  enable_story_reviewer:      true,
};

export default function StoryForm({ onSubmit, isGenerating, logoSrc }) {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [wikiOpen, setWikiOpen] = useState(false);
  const [isSuggesting, setIsSuggesting] = useState(false);
  const [suggestError, setSuggestError] = useState(null);

  const hasWikiTopic = form.wikipedia_topic.trim().length > 0;
  const isFullMode   = hasWikiTopic && form.wikipedia_mode === 'full';

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
    // Only send wikipedia fields when a topic is actually provided
    if (!hasWikiTopic) {
      delete payload.wikipedia_topic;
      delete payload.wikipedia_mode;
    }
    onSubmit(payload);
  }

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div className={styles.container}>
      <h2 className={styles.title}>
        {logoSrc && <img src={logoSrc} alt="" className={styles.titleIcon} />}
        Create a Children's Story
      </h2>
      <p className={styles.subtitle}>
        Fill in the details below and let the AI agents craft a magical illustrated story!
      </p>

      <form onSubmit={handleSubmit}>

        {/* ── Wikipedia RAG section (collapsible, collapsed by default) ─── */}
        <button
          type="button"
          className={`${styles.collapsibleHeader} ${wikiOpen ? styles.collapsibleHeaderOpen : ''}`}
          onClick={() => setWikiOpen(o => !o)}
          aria-expanded={wikiOpen}
          aria-controls="wikipedia-section"
        >
          <span className={styles.collapsibleTitle}>🌐 Wikipedia Topic (optional)</span>
          <span className={styles.collapsibleHint}>
            {wikiOpen ? 'Hide' : 'Base your story on a real-world topic'}
          </span>
          <span className={styles.collapsibleChevron} aria-hidden="true">▾</span>
        </button>

        {wikiOpen && (
          <div id="wikipedia-section" className={styles.collapsibleBody}>
            <div className={styles.field}>
              <label className={styles.label}>Real-world Topic</label>
              <input
                className={styles.input}
                type="text"
                placeholder="e.g. Marie Curie, Moon landing, Photosynthesis"
                value={form.wikipedia_topic}
                onChange={handleField('wikipedia_topic')}
              />
              <p className={styles.hint}>
                Enter a topic and we'll pull real facts from Wikipedia to create or inspire the story.
              </p>
            </div>

            <div className={styles.field}>
              <label className={`${styles.label} ${!hasWikiTopic ? styles.labelDisabled : ''}`}>How should Wikipedia content be used?</label>
              <div className={`${styles.modeCards} ${!hasWikiTopic ? styles.modeCardsDisabled : ''}`}>

                  <label className={`${styles.modeCard} ${form.wikipedia_mode === 'full' && hasWikiTopic ? styles.modeCardSelected : ''}`}>
                    <input
                      type="radio"
                      name="wikipedia_mode"
                      value="full"
                      checked={form.wikipedia_mode === 'full'}
                      onChange={handleField('wikipedia_mode')}
                      className={styles.modeRadio}
                    />
                    <span className={styles.modeIcon}>📖</span>
                    <span className={styles.modeLabel}>Full Wikipedia Story</span>
                    <span className={styles.modeDesc}>
                      The AI creates the <strong>entire story</strong> — characters, setting, moral,
                      and plot — from the Wikipedia article. The fields below will be ignored.
                    </span>
                  </label>

                  <label className={`${styles.modeCard} ${form.wikipedia_mode === 'influence' && hasWikiTopic ? styles.modeCardSelected : ''}`}>
                    <input
                      type="radio"
                      name="wikipedia_mode"
                      value="influence"
                      checked={form.wikipedia_mode === 'influence'}
                      onChange={handleField('wikipedia_mode')}
                      className={styles.modeRadio}
                    />
                    <span className={styles.modeIcon}>✨</span>
                    <span className={styles.modeLabel}>Wikipedia-Influenced Story</span>
                    <span className={styles.modeDesc}>
                      Your characters, setting, and moral are kept — Wikipedia facts are woven in
                      as <strong>background inspiration</strong>.
                    </span>
                  </label>

              </div>
            </div>
          </div>
        )}

        {/* ── Surprise Me (auto-fill text fields with an LLM-generated seed) ── */}
        <div className={styles.surpriseRow}>
          <button
            type="button"
            className={styles.btnSurprise}
            onClick={handleSurpriseMe}
            disabled={isSuggesting || isGenerating || isFullMode}
            title={isFullMode
              ? 'Auto-fill is disabled in Full Wikipedia Story mode — those fields will be derived from the article.'
              : 'Generate a fresh, creative set of values for every text field below.'}
          >
            {isSuggesting ? (
              <>
                <span className="spinner" />
                Dreaming up a new story…
              </>
            ) : (
              <>✨ Surprise Me — Auto-fill the Form</>
            )}
          </button>
          <p className={styles.surpriseHint}>
            Replaces the character, setting, moral, problem, and details fields with a brand-new idea.
            Wikipedia and bonus settings are left alone.
          </p>
          {suggestError && (
            <p className={styles.surpriseError} role="alert">{suggestError}</p>
          )}
        </div>

        <hr className={styles.divider} />

        {/* ── Main characters section ───────────────────────────────── */}
        <div className={`${styles.sectionTitle} ${isFullMode ? styles.sectionDisabled : ''}`}>🐰 Characters</div>

        {isFullMode && (
          <p className={styles.disabledNotice}>
            Not used in Full Wikipedia Story mode — the AI will create characters from the article.
          </p>
        )}

        <fieldset disabled={isFullMode} className={styles.fieldset}>

          <div className={styles.field}>
            <label className={styles.label}>
              Main Character Name {!isFullMode && <span className={styles.required}>*</span>}
            </label>
            <input
              className={styles.input}
              type="text"
              placeholder="e.g. Benny the Brave Bunny"
              value={form.main_character}
              onChange={handleField('main_character')}
              required={!isFullMode}
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
        <div className={`${styles.sectionTitle} ${isFullMode ? styles.sectionDisabled : ''}`}>🌿 The World & Story</div>

        {isFullMode && (
          <p className={styles.disabledNotice}>
            Not used in Full Wikipedia Story mode — the AI will derive setting, moral, and plot from the article.
          </p>
        )}

        <fieldset disabled={isFullMode} className={styles.fieldset}>

          <div className={styles.field}>
            <label className={styles.label}>
              Setting {!isFullMode && <span className={styles.required}>*</span>}
            </label>
            <input
              className={styles.input}
              type="text"
              placeholder="e.g. A magical forest with talking trees and glowing fireflies"
              value={form.setting}
              onChange={handleField('setting')}
              required={!isFullMode}
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label}>
              Moral of the Story {!isFullMode && <span className={styles.required}>*</span>}
            </label>
            <input
              className={styles.input}
              type="text"
              placeholder="e.g. True courage means helping others even when you're scared"
              value={form.moral}
              onChange={handleField('moral')}
              required={!isFullMode}
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label}>
              Main Problem / Central Challenge {!isFullMode && <span className={styles.required}>*</span>}
            </label>
            <textarea
              className={styles.textarea}
              placeholder="e.g. A mysterious fog has covered the forest, and the animals can't find their way home"
              value={form.main_problem}
              onChange={handleField('main_problem')}
              required={!isFullMode}
            />
          </div>

        </fieldset>

        <hr className={styles.divider} />

        {/* ── Additional details ────────────────────────────────────── */}
        <div className={`${styles.sectionTitle} ${isFullMode ? styles.sectionDisabled : ''}`}>✏️ Additional Details (optional)</div>

        <fieldset disabled={isFullMode} className={styles.fieldset}>
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

        {/* ── Bonus content ─────────────────────────────────────────── */}
        <div className={styles.sectionTitle}>🌟 Bonus Content</div>

        <div className={styles.checkboxGroup}>
          <label className={styles.checkboxLabel}>
            <input
              type="checkbox"
              className={styles.checkboxInput}
              checked={form.include_look_and_find}
              onChange={e => setForm(prev => ({ ...prev, include_look_and_find: e.target.checked }))}
            />
            <span className={styles.checkboxText}>
              <strong>🔎 Generate Look &amp; Find Activity Page</strong>
              <span className={styles.checkboxHint}>Challenges the child to find 3–5 hidden items across the story's illustrations</span>
            </span>
          </label>

          <label className={styles.checkboxLabel}>
            <input
              type="checkbox"
              className={styles.checkboxInput}
              checked={form.include_character_glossary}
              onChange={e => setForm(prev => ({ ...prev, include_character_glossary: e.target.checked }))}
            />
            <span className={styles.checkboxText}>
              <strong>📖 Generate Character Glossary</strong>
              <span className={styles.checkboxHint}>Adds a "Meet the Characters" page with fun descriptions of each character</span>
            </span>
          </label>
        </div>

        {/* ── Advanced Options ──────────────────────────────────────── */}
        <div className={styles.sectionTitle}>⚙️ Advanced Options</div>

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
              '🪄 Create My Story!'
            )}
          </button>
        </div>

      </form>
    </div>
  );
}
