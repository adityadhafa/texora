import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { getHardware, setDevice, type Hardware } from './engineClient';

const DEVICE_LABEL_KEY: Record<string, string> = {
  cpu: 'hardware.deviceCpu',
  cuda: 'hardware.deviceCuda',
  mps: 'hardware.deviceMps',
};

/**
 * Settings section for hardware: shows detected devices + the current selection and lets the
 * user override the execution device. All engine access goes through `engineClient`; all
 * strings via i18next.
 */
export default function SettingsHardware(): React.JSX.Element {
  const { t } = useTranslation();
  const [hardware, setHardware] = useState<Hardware | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHardware()
      .then(setHardware)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  const onChange = useCallback(
    (device: string) => {
      setDevice(device)
        .then(setHardware)
        .catch((e: unknown) => setError(String(e)));
    },
    [],
  );

  return (
    <section className="flex flex-col gap-3 text-fg" aria-label={t('hardware.title')}>
      <h2 className="text-lg font-semibold">{t('hardware.title')}</h2>

      {error ? (
        <p className="text-sm text-red-400">{error}</p>
      ) : hardware ? (
        <div className="flex flex-col gap-2 text-sm">
          <label className="flex items-center gap-2">
            <span className="text-muted">{t('hardware.device')}</span>
            <select
              aria-label={t('hardware.override')}
              value={hardware.selected}
              onChange={(e) => onChange(e.target.value)}
              className="rounded border border-muted/40 bg-surface px-2 py-1"
            >
              {hardware.devices.map((d) => (
                <option key={d} value={d}>
                  {t(DEVICE_LABEL_KEY[d] ?? d)}
                </option>
              ))}
            </select>
          </label>
          <p className="text-muted">{t('hardware.cpuSlowNote')}</p>
        </div>
      ) : (
        <p className="text-sm text-muted">…</p>
      )}
    </section>
  );
}
