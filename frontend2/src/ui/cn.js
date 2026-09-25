// Склейка классов: cn('a', cond && 'b', undefined) → 'a b'.
export function cn(...parts) {
  return parts.filter(Boolean).join(' ')
}

// Склонение по числу — с учётом языка (i18n): plural(5, ['ребёнок', 'ребёнка', 'детей']).
export { plural } from '../i18n'

export function initials(fullName = '') {
  return fullName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(part => part[0].toUpperCase())
    .join('') || '·'
}
