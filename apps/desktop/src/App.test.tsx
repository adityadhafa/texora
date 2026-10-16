import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import App from './App';

afterEach(() => {
  cleanup();
  document.documentElement.classList.remove('dark');
});

describe('App', () => {
  it('renders the Texora home heading', () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: 'Texora' })).toBeTruthy();
  });

  it('toggles the theme class on the document root', () => {
    render(<App />);
    const toggle = screen.getByRole('button', { name: /toggle color theme/i });
    const wasDark = document.documentElement.classList.contains('dark');

    fireEvent.click(toggle);

    expect(document.documentElement.classList.contains('dark')).toBe(!wasDark);
  });
});
