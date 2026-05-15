import { useState, useEffect } from 'react';
import './styles/global.css';
import logoSrc from './assets/logo.png';
import brandSrc from './assets/image.png';
import StoryForm from './components/StoryForm';
import StoryGallery from './components/StoryGallery';
import ProgressTracker from './components/ProgressTracker';
import StoryBook from './components/StoryBook';
import { useStoryGeneration } from './hooks/useStoryGeneration';

/**
 * View states:
 *   "form"        — initial input form (tabbed: create / saved stories)
 *   "generating"  — workflow is running; showing progress tracker
 *   "storybook"   — finished; split layout: tracker sidebar + storybook
 */
function App() {
  const [view, setView] = useState('form');
  const [formTab, setFormTab] = useState('create'); // 'create' | 'saved'
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const { story, progress, details, sessionId, isGenerating, error, generate, reset, loadDemoStory } =
    useStoryGeneration();

  // Transition to the storybook view once the story is ready
  useEffect(() => {
    if (!story || view !== 'generating') return;
    const timer = setTimeout(() => setView('storybook'), 600);
    return () => clearTimeout(timer);
  }, [story, view]);

  async function handleSubmit(formData) {
    setSidebarOpen(true);
    setView('generating');
    await generate(formData);
  }

  function handleReset() {
    reset();
    setView('form');
  }

  async function handleLoadDemo(storyId) {
    setSidebarOpen(true);
    await loadDemoStory(storyId);
    setView('storybook');
  }

  async function handleSaveStory() {
    if (!story) return;
    // Assemble the progress/detail events into the format expected by the backend
    const events = [
      ...progress.map(p => ({ type: 'progress', data: p })),
      ...details.map(d => ({ type: 'detail', data: d })),
    ];
    const payload = {
      meta: {
        title: story.title,
        description: story.moral_summary,
        moral: story.moral_summary,
      },
      story,
      events,
      // Echo back the server-assigned session id so the backend can promote
      // the per-session draft images folder rather than re-decoding base64.
      session_id: sessionId,
    };
    const res = await fetch('/api/demo-stories', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`Save failed (${res.status})`);
  }

  return (
    <>
      {/* ── Header ─────────────────────────────────────────────────── */}
      <header className="app-header">
        <h1 onClick={handleReset} style={{ cursor: 'pointer' }}><img src={brandSrc} alt="Zava" className="header-brand" /> Publishing - Children's Story Studio</h1>
      </header>

      {/* ── Main content ───────────────────────────────────────────── */}
      <main className={`app-main${view === 'storybook' ? ' app-main--split' : ''}`}>

        {view === 'form' && (
          <div className="card">
            <div className="tab-bar">
              <button
                className={`tab-btn${formTab === 'create' ? ' tab-btn--active' : ''}`}
                onClick={() => setFormTab('create')}
              >
                ✏️ Create Story
              </button>
              <button
                className={`tab-btn${formTab === 'saved' ? ' tab-btn--active' : ''}`}
                onClick={() => setFormTab('saved')}
              >
                📚 Saved Stories
              </button>
            </div>

            {formTab === 'create' && (
              <StoryForm onSubmit={handleSubmit} isGenerating={isGenerating} logoSrc={logoSrc} />
            )}

            {formTab === 'saved' && (
              <StoryGallery onLoadStory={handleLoadDemo} />
            )}
          </div>
        )}

        {view === 'generating' && (
          <div className="card">
            <ProgressTracker
              progress={progress}
              details={details}
              error={error}
              mode="full"
            />
            {error && (
              <div style={{ display: 'flex', justifyContent: 'center', marginTop: 24 }}>
                <button className="btn-secondary" onClick={handleReset}>
                  ← Try Again
                </button>
              </div>
            )}
          </div>
        )}

        {view === 'storybook' && story && (
          <>
            {/* Left sidebar — collapsible generation log */}
            <aside className={`tracker-sidebar${sidebarOpen ? ' tracker-sidebar--open' : ''}`}>
              <ProgressTracker
                progress={progress}
                details={details}
                error={error}
                mode="sidebar"
                isCollapsed={!sidebarOpen}
                onToggle={() => setSidebarOpen(o => !o)}
                reviewNotes={story.review_notes}
              />
            </aside>

            {/* Right content — storybook */}
            <div className="storybook-area">
              {/* Reopen tab — only shown when sidebar is hidden */}
              {!sidebarOpen && (
                <button
                  className="sidebar-reopener"
                  onClick={() => setSidebarOpen(true)}
                  title="Show generation log"
                >
                  📋
                </button>
              )}
              <StoryBook story={story} onReset={handleReset} onSave={handleSaveStory} />
            </div>
          </>
        )}
      </main>
    </>
  );
}

export default App;

