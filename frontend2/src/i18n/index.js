/**
 * Языки frontend2 (TRU-92): русский (исходный), казахский, английский.
 *
 * Как в gettext: в коде пишется русский текст — t('Добавить ребёнка'), а
 * словари kk.json / en.json переводят его. Нет перевода — показывается
 * русский, экран не ломается. Подстановки: t('Свободно {n} мест', { n: 3 }).
 *
 * Переключение без перезагрузки: setLang() меняет язык и оповещает
 * подписчиков, App по useLang() перемонтирует экраны. Поэтому в константах
 * модулей t() не вызывается при импорте: подписи — геттеры
 * (get label() { return t('…') }) или русский текст, переводимый при показе.
 * Термины — как в словарях старого веба (backend/i18n_src).
 */
import { useSyncExternalStore } from 'react'
import en from './en.json'
import kk from './kk.json'

export const LANGUAGES = [
  { code: 'ru', short: 'RU', label: 'Русский', locale: 'ru-RU' },
  { code: 'kk', short: 'KK', label: 'Қазақша', locale: 'kk-KZ' },
  { code: 'en', short: 'EN', label: 'English', locale: 'en-US' },
]
const STORAGE_KEY = 'kc:lang'
const DICTIONARIES = { kk, en }

function readLang() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (LANGUAGES.some(l => l.code === saved)) return saved
  } catch { /* приватный режим — язык по умолчанию */ }
  return 'ru'
}

export let lang = readLang()
export let locale = localeOf(lang)
if (typeof document !== 'undefined') document.documentElement.lang = lang

function localeOf(code) {
  return LANGUAGES.find(l => l.code === code).locale
}

const listeners = new Set()

export function setLang(code) {
  if (code === lang || !LANGUAGES.some(l => l.code === code)) return
  lang = code
  locale = localeOf(code)
  document.documentElement.lang = code
  try { localStorage.setItem(STORAGE_KEY, code) } catch { /* не запомнится */ }
  listeners.forEach(listener => listener())
}

function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Текущий язык; компонент перерисуется при смене. */
export function useLang() {
  return useSyncExternalStore(subscribe, () => lang)
}

function fill(text, vars) {
  if (!vars) return text
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in vars ? String(vars[name]) : match))
}

/** Перевод русского текста на текущий язык. */
export function t(text, vars) {
  if (text == null || text === '') return text
  const dict = DICTIONARIES[lang]
  const translated = dict?.[text]
  return fill(typeof translated === 'string' ? translated : text, vars)
}

/**
 * Склонение по числу. В коде — русские формы, как раньше:
 * plural(5, ['ребёнок', 'ребёнка', 'детей']). Для kk/en формы берутся из
 * словаря по первой русской форме: в kk — одна форма (после числа в
 * казахском единственное число), в en — [one, other].
 */
export function plural(n, forms) {
  const [one, few, many] = forms
  if (lang === 'ru') {
    const mod10 = n % 10
    const mod100 = n % 100
    if (mod10 === 1 && mod100 !== 11) return one
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few
    return many
  }
  const translated = DICTIONARIES[lang]?.[`plural:${one}`]
  if (Array.isArray(translated)) return n === 1 ? translated[0] : translated[translated.length - 1]
  if (typeof translated === 'string') return translated
  return many
}
