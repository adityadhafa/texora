import { useTheme } from './theme';

/**
 * Blank Home screen for the Texora skeleton. Intentionally minimal: it only
 * demonstrates the dark/light theme tokens wired through Tailwind. Engine
 * wiring, status, and any ML/business logic arrive in later tasks.
 */
function App(): JSX.Element {
  const { theme, toggleTheme } = useTheme();

  return (
    <main className="flex h-full flex-col items-center justify-center gap-6 bg-bg text-fg">
      <h1 className="text-3xl font-semibold tracking-tight">Texora</h1>
      <p className="max-w-md text-center text-muted">
        Offline-first OCR for mathematical and scientific documents.
      </p>
      <button
        type="button"
        onClick={toggleTheme}
        className="rounded-md border border-muted/40 bg-surface px-4 py-2 text-sm font-medium text-fg transition-colors hover:border-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        aria-label="Toggle color theme"
      >
        Theme: {theme === 'dark' ? 'Dark' : 'Light'}
      </button>
    </main>
  );
}

export default App;
