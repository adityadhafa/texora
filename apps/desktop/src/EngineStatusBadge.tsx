import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  getEngineStatus,
  subscribeEngineStatus,
  type EngineState,
  type EngineStatus,
} from './engineClient';

/** Tailwind dot color per engine state. */
const DOT_CLASS: Record<EngineState, string> = {
  starting: 'bg-amber-400',
  healthy: 'bg-emerald-500',
  unhealthy: 'bg-red-500',
  restarting: 'bg-amber-400',
  stopped: 'bg-muted',
};

/**
 * Live engine status badge. Reads the initial status via the typed client, then
 * subscribes to `engine://status` updates. All strings come from i18next; the
 * component never touches the Tauri bridge directly.
 */
function EngineStatusBadge(): React.JSX.Element {
  const { t } = useTranslation();
  const [status, setStatus] = useState<EngineStatus>({ state: 'starting' });

  useEffect(() => {
    let active = true;

    getEngineStatus()
      .then((initial) => {
        if (active) {
          setStatus(initial);
        }
      })
      .catch(() => {
        // Before the supervisor answers, keep the default `starting` state.
      });

    const unlistenPromise = subscribeEngineStatus((next) => {
      if (active) {
        setStatus(next);
      }
    });

    return () => {
      active = false;
      void unlistenPromise.then((unlisten) => {
        unlisten();
      });
    };
  }, []);

  const stateLabel = t(`engine.state.${status.state}`);

  return (
    <div
      className="flex items-center gap-2 rounded-full border border-muted/40 bg-surface px-3 py-1 text-xs font-medium text-fg"
      role="status"
      aria-live="polite"
      aria-label={`${t('engine.label')}: ${stateLabel}`}
    >
      <span
        className={`inline-block h-2 w-2 rounded-full ${DOT_CLASS[status.state]}`}
        aria-hidden="true"
      />
      <span>{t('engine.label')}</span>
      <span className="text-muted">{stateLabel}</span>
    </div>
  );
}

export default EngineStatusBadge;
