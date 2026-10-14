import { Fragment, type ReactNode } from 'react'

/**
 * The little Markdown a review uses: headings, paragraphs, bullet and numbered lists, **bold**, *italics*, links,
 * and [n] citations, which jump to reference n (``ref-n`` on the page). Anything else shows as plain text.
 */
export function Markdown({ text, idPrefix = 'ref' }: { text: string; idPrefix?: string }) {
  const blocks: ReactNode[] = []
  const lines = text.split('\n')
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) {
      i++
      continue
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      const level = heading[1].length
      const cls = level <= 2 ? 'mt-2 text-[15px] font-semibold text-fg' : 'mt-1 text-[14px] font-semibold text-fg'
      blocks.push(level <= 2 ? <h3 key={i} className={cls}>{inline(heading[2], idPrefix)}</h3> : <h4 key={i} className={cls}>{inline(heading[2], idPrefix)}</h4>)
      i++
      continue
    }
    const ordered = /^\d+\.\s/.test(line)
    if (ordered || /^[-*]\s/.test(line)) {
      const items: string[] = []
      while (i < lines.length && (ordered ? /^\d+\.\s/ : /^[-*]\s/).test(lines[i])) {
        items.push(lines[i].replace(ordered ? /^\d+\.\s+/ : /^[-*]\s+/, ''))
        i++
      }
      const List = ordered ? 'ol' : 'ul'
      blocks.push(
        <List key={i} className={ordered ? 'grid list-decimal gap-1.5 pl-5' : 'grid list-disc gap-1.5 pl-5'}>
          {items.map((item, k) => <li key={k}>{inline(item, idPrefix)}</li>)}
        </List>,
      )
      continue
    }
    const para: string[] = []
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|[-*]\s|\d+\.\s)/.test(lines[i])) {
      para.push(lines[i].trim())
      i++
    }
    blocks.push(<p key={i}>{inline(para.join(' '), idPrefix)}</p>)
  }
  return <div className="grid gap-3 text-[14px] leading-relaxed text-fg-2">{blocks}</div>
}

const TOKEN = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[\d+(?:\s*,\s*\d+)*\]|https?:\/\/[^\s)]+)/g

function inline(text: string, idPrefix: string): ReactNode {
  const parts = text.split(TOKEN)
  return parts.map((part, k) => {
    if (!part) return null
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={k} className="font-semibold text-fg">{part.slice(2, -2)}</strong>
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) return <em key={k}>{part.slice(1, -1)}</em>
    if (/^\[\d/.test(part)) {
      const nums = part.slice(1, -1).split(',').map((n) => n.trim())
      return (
        <span key={k} className="whitespace-nowrap">
          [{nums.map((n, j) => (
            <Fragment key={n}>
              {j > 0 && ', '}
              <a href={`#${idPrefix}-${n}`} className="font-mono text-[12px] text-accent-ink hover:underline">{n}</a>
            </Fragment>
          ))}]
        </span>
      )
    }
    if (/^https?:\/\//.test(part)) return <a key={k} href={part} target="_blank" rel="noopener noreferrer" className="break-all text-accent-ink hover:underline">{part}</a>
    return <Fragment key={k}>{part}</Fragment>
  })
}
