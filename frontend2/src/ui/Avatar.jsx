import { cn, initials } from './cn'

// Мягкие фоны для инициалов — цвет стабилен для одного и того же имени,
// чтобы в длинном списке детей глазу было за что зацепиться.
const PALETTE = [
  'bg-brand-100 text-brand-700',
  'bg-info-50 text-info-600',
  'bg-success-50 text-success-600',
  'bg-warning-50 text-warning-600',
  'bg-surface-muted text-ink-muted',
]

function paletteFor(name = '') {
  let hash = 0
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) | 0
  return PALETTE[Math.abs(hash) % PALETTE.length]
}

const SIZES = { sm: 'size-8 text-xs', md: 'size-10 text-sm', lg: 'size-16 text-lg' }

export function Avatar({ name, src, size = 'sm', className }) {
  if (src) {
    return <img src={src} alt="" className={cn('shrink-0 rounded-full object-cover', SIZES[size], className)} />
  }
  return (
    <span className={cn('inline-flex shrink-0 items-center justify-center rounded-full font-bold', SIZES[size], paletteFor(name), className)}>
      {initials(name)}
    </span>
  )
}
