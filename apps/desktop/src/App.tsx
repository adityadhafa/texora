import { useTranslation } from 'react-i18next';

import EngineStatusBadge from './EngineStatusBadge';
import { useTheme } from './theme';

/**
 * Home screen for the Texora skeleton. Shows the live engine status badge and a
 * dark/light theme toggle. All user-facing strings go through i18next; no ML or
 * business logic lives in the UI layer.
 */
function App(): React.JSX.Element {
  const { t } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const themeLabel = theme === 'dark' ? t('theme.dark') : t('theme.light');

  return (
    <main className="flex h-full flex-col items-center justify-center gap-6 bg-bg text-fg">
      <div className="absolute right-4 top-4">
        <EngineStatusBadge />
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">Texora</h1>
      <p className="max-w-md text-center text-muted">{t('app.tagline')}</p>
      <button
        type="button"
        onClick={toggleTheme}
        className="rounded-md border border-muted/40 bg-surface px-4 py-2 text-sm font-medium text-fg transition-colors hover:border-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        aria-label={t('theme.toggle')}
      >
        {`${t('theme.toggle')}: ${themeLabel}`}
      </button>
    </main>
  );
}

export default App;
