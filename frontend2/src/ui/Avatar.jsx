import { cn, initials } from './cn'

// Мягкие фоны для инициалов — цвет стабилен для одного и того же имени,
// чтобы в длинном списке детей глазу было за что зацепиться.
// Яркие градиенты (TRU-91): у каждого имени свой — в списке детей глазу
// есть за что зацепиться.
const PALETTE = [
  'bg-[linear-gradient(135deg,#ff9d8a,#e0567a)]',
  'bg-[linear-gradient(135deg,#8ec5ff,#6e7cf5)]',
  'bg-[linear-gradient(135deg,#7fe0b5,#2faf7f)]',
  'bg-[linear-gradient(135deg,#ffd27a,#f29a3a)]',
  'bg-[linear-gradient(135deg,#c9a2ff,#9b6bf0)]',
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
    <span className={cn('inline-flex shrink-0 items-center justify-center rounded-full font-bold text-white', SIZES[size], paletteFor(name), className)}>
      {initials(name)}
    </span>
  )
}
