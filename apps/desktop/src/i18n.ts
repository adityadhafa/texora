/**
 * i18next setup. Indonesian (`id`) is the default language; English (`en`) is
 * provided as a fallback. All user-facing strings must resolve through here —
 * no hard-coded UI text (see `.kiro/steering/coding-standards.md`).
 */
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import en from './locales/en.json';
import id from './locales/id.json';

export const defaultLanguage = 'id';

export const resources = {
  id: { translation: id },
  en: { translation: en },
} as const;

void i18n.use(initReactI18next).init({
  resources,
  lng: defaultLanguage,
  fallbackLng: 'en',
  interpolation: {
    // React already escapes output.
    escapeValue: false,
  },
});

export default i18n;
