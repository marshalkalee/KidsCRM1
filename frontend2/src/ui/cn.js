// Склейка классов: cn('a', cond && 'b', undefined) → 'a b'.
export function cn(...parts) {
  return parts.filter(Boolean).join(' ')
}

// Русское склонение по числу: plural(5, ['ребёнок', 'ребёнка', 'детей']).
export function plural(n, [one, few, many]) {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few
  return many
}

export function initials(fullName = '') {
  return fullName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(part => part[0].toUpperCase())
    .join('') || '·'
}
