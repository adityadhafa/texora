import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { invoke } from '@tauri-apps/api/core';

import SettingsHardware from './SettingsHardware';
import './i18n';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn() }));

const invokeMock = vi.mocked(invoke);

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

describe('SettingsHardware', () => {
  it('renders the detected devices and the CPU-slower note', async () => {
    invokeMock.mockResolvedValue(JSON.stringify({ devices: ['cpu', 'cuda'], selected: 'cpu' }));
    render(<SettingsHardware />);

    await waitFor(() => expect(screen.getByRole('combobox')).toBeTruthy());
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    expect(select.value).toBe('cpu');
    // CPU-slower note present (id default).
    expect(screen.getByText(/lebih lambat|slower/i)).toBeTruthy();
  });

  it('calls setDevice when the selection changes', async () => {
    invokeMock.mockResolvedValue(JSON.stringify({ devices: ['cpu', 'cuda'], selected: 'cpu' }));
    render(<SettingsHardware />);
    await waitFor(() => expect(screen.getByRole('combobox')).toBeTruthy());

    invokeMock.mockResolvedValueOnce(
      JSON.stringify({ devices: ['cpu', 'cuda'], selected: 'cuda' }),
    );
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'cuda' } });

    await waitFor(() =>
      expect(invokeMock).toHaveBeenCalledWith('set_device', { device: 'cuda' }),
    );
  });
});
