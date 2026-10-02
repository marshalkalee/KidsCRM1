import { Fragment } from 'react'
import { Link } from 'react-router-dom'
import { cn } from '../../ui'

/*
 * Ответ ИИ — небольшой Markdown: абзацы, списки, **жирный**, ссылки.
 * Ссылки — только на экраны CRM (/children/…), внешние показываются текстом.
 */
const INLINE = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\))/g

// «389 000 ₸» не разрывается между строк.
const keepNumbers = text => text.replace(/(\d) (?=\d{3}(?!\d))/g, '$1\u00a0').replace(/(\d) ₸/g, '$1\u00a0₸')

function Inline({ text }) {
  return keepNumbers(text).split(INLINE).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part)
    if (link) {
      return link[2].startsWith('/') && !link[2].startsWith('//')
        ? <Link key={i} to={link[2]} className="font-semibold text-[#7c3aed] underline decoration-[#ddd6fe] underline-offset-2 hover:decoration-[#7c3aed]">{link[1]}</Link>
        : <Fragment key={i}>{link[1]}</Fragment>
    }
    return <Fragment key={i}>{part}</Fragment>
  })
}

export default function Markdown({ text }) {
  const blocks = []
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd()
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line)
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    const last = blocks[blocks.length - 1]
    if (bullet || numbered) {
      const kind = bullet ? 'ul' : 'ol'
      const item = (bullet || numbered)[1]
      if (last?.kind === kind) last.items.push(item)
      else blocks.push({ kind, items: [item] })
    } else if (/^#{1,4}\s+/.test(line)) {
      blocks.push({ kind: 'h', text: line.replace(/^#{1,4}\s+/, '') })
    } else if (line.trim()) {
      if (last?.kind === 'p') last.lines.push(line)
      else blocks.push({ kind: 'p', lines: [line] })
    } else {
      blocks.push({ kind: 'gap' })
    }
  }
  return (
    <div className="space-y-2 leading-relaxed">
      {blocks.map((b, i) => {
        if (b.kind === 'gap') return null
        if (b.kind === 'h') return <p key={i} className="font-bold"><Inline text={b.text} /></p>
        if (b.kind === 'p') return <p key={i}>{b.lines.map((l, j) => <Fragment key={j}>{j > 0 && <br />}<Inline text={l} /></Fragment>)}</p>
        const List = b.kind
        return (
          <List key={i} className={cn('space-y-1 pl-5', b.kind === 'ul' ? 'list-disc marker:text-[#a78bfa]' : 'list-decimal marker:font-semibold marker:text-ink-muted')}>
            {b.items.map((item, j) => <li key={j}><Inline text={item} /></li>)}
          </List>
        )
      })}
    </div>
  )
}
