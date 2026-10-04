import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import ur from './locales/ur.json'

export const LANGUAGES = ['en', 'ur'] as const
export type AppLanguage = (typeof LANGUAGES)[number]
export const RTL_LANGUAGES: AppLanguage[] = ['ur']
const STORAGE_KEY = 'crm.language'

function storedLanguage(): AppLanguage {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    if (value && (LANGUAGES as readonly string[]).includes(value)) return value as AppLanguage
  } catch {
    /* storage unavailable */
  }
  return 'en'
}

export const isRtl = (lang: string) => RTL_LANGUAGES.includes(lang as AppLanguage)

/** Applies lang/dir to <html> so CSS logical properties and the Urdu font take effect. */
function applyDocumentLanguage(lang: string) {
  document.documentElement.lang = lang
  document.documentElement.dir = isRtl(lang) ? 'rtl' : 'ltr'
}

i18n.on('languageChanged', (lang) => {
  applyDocumentLanguage(lang)
  try {
    localStorage.setItem(STORAGE_KEY, lang)
  } catch {
    /* storage unavailable */
  }
})

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, ur: { translation: ur } },
  lng: storedLanguage(),
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
})
applyDocumentLanguage(i18n.language)

export default i18n
