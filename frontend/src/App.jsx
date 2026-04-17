import { useState, useEffect } from 'react';
import './styles/global.css';
import logoSrc from './assets/logo.png';
import StoryForm from './components/StoryForm';
import ProgressTracker from './components/ProgressTracker';
import StoryBook from './components/StoryBook';
import { useStoryGeneration } from './hooks/useStoryGeneration';

/**
 * View states:
 *   "form"        — initial input form
 *   "generating"  — workflow is running; showing progress tracker
 *   "storybook"   — finished; split layout: tracker sidebar + storybook
 */
function App() {
  const [view, setView] = useState('form');
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const { story, progress, details, isGenerating, error, generate, reset } =
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

  return (
    <>
      {/* ── Header ─────────────────────────────────────────────────── */}
      <header className="app-header">
        <img src={logoSrc} alt="Logo" className="header-icon" />
        <h1>Zava Publishing - Children's Story Studio</h1>
      </header>

      {/* ── Main content ───────────────────────────────────────────── */}
      <main className={`app-main${view === 'storybook' ? ' app-main--split' : ''}`}>

        {view === 'form' && (
          <div className="card">
            <StoryForm onSubmit={handleSubmit} isGenerating={isGenerating} />
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
              <StoryBook story={story} onReset={handleReset} />
            </div>
          </>
        )}
      </main>
    </>
  );
}

export default App;

