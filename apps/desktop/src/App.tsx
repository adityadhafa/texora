import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import ConvertPdf from './ConvertPdf';
import EngineStatusBadge from './EngineStatusBadge';
import { recognizeSnip, subscribeSnipCaptured, type SnipResult } from './engineClient';
import SettingsHardware from './SettingsHardware';
import SnipPopup from './SnipPopup';
import { useTheme } from './theme';

type View = 'home' | 'convert';

/**
 * Home screen for the Texora skeleton + M2 snip tool. Shows the live engine status badge, a
 * dark/light theme toggle, the hardware settings, and the snip result popup. Capture events
 * (Ctrl+Shift+M, fired from Rust) flow in via `subscribeSnipCaptured` → `recognizeSnip`,
 * both through the single typed client. No ML/business logic lives in the UI.
 */
function App(): React.JSX.Element {
  const { t } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const themeLabel = theme === 'dark' ? t('theme.dark') : t('theme.light');

  const [view, setView] = useState<View>('home');
  const [snip, setSnip] = useState<SnipResult | null>(null);
  const [snipError, setSnipError] = useState<string | null>(null);
  const isDisplay = true; // M2: whole-monitor capture is treated as display math.

  const onCaptured = useCallback(
    (pngBase64OrError: string) => {
      setSnipError(null);
      if (pngBase64OrError.startsWith('ERROR:')) {
        setSnipError(t('snip.error.capture'));
        return;
      }
      recognizeSnip(pngBase64OrError, isDisplay)
        .then(setSnip)
        .catch(() => setSnipError(t('snip.error.engineNotReady')));
    },
    [t, isDisplay],
  );

  useEffect(() => {
    const unlistenPromise = subscribeSnipCaptured(onCaptured);
    return () => {
      void unlistenPromise.then((unlisten) => unlisten());
    };
  }, [onCaptured]);

  if (view === 'convert') {
    return (
      <>
        <div className="absolute right-4 top-4 z-10">
          <EngineStatusBadge />
        </div>
        <ConvertPdf onBack={() => setView('home')} />
        {snip ? (
          <div className="absolute inset-0 flex items-center justify-center bg-black/30">
            <SnipPopup result={snip} isDisplay={isDisplay} onClose={() => setSnip(null)} />
          </div>
        ) : null}
      </>
    );
  }

  return (
    <main className="flex h-full flex-col items-center justify-center gap-6 bg-bg text-fg">
      <div className="absolute right-4 top-4">
        <EngineStatusBadge />
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">Texora</h1>
      <p className="max-w-md text-center text-muted">{t('app.tagline')}</p>
      <p className="text-sm text-muted">{t('snip.hotkeyHint')}</p>
      <button
        type="button"
        onClick={() => setView('convert')}
        className="rounded-md border border-accent bg-accent/10 px-4 py-2 text-sm font-medium text-fg transition-colors hover:bg-accent/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        {t('home.convert')}
      </button>
      <button
        type="button"
        onClick={toggleTheme}
        className="rounded-md border border-muted/40 bg-surface px-4 py-2 text-sm font-medium text-fg transition-colors hover:border-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        aria-label={t('theme.toggle')}
      >
        {`${t('theme.toggle')}: ${themeLabel}`}
      </button>

      <div className="w-[32rem] max-w-full">
        <SettingsHardware />
      </div>

      {snipError ? <p className="text-sm text-red-400">{snipError}</p> : null}

      {snip ? (
        <div className="absolute inset-0 flex items-center justify-center bg-black/30">
          <SnipPopup result={snip} isDisplay={isDisplay} onClose={() => setSnip(null)} />
        </div>
      ) : null}
    </main>
  );
}

export default App;
