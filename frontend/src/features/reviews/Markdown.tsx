import { Fragment, type ReactNode } from 'react'

const BLOCK_START = /^(#{1,4}\s|[-*]\s|\d+\.\s|```|>\s?|\|)/

/**
 * The Markdown reviews and chats use: headings, paragraphs, bullet and numbered lists, code blocks, quotes, tables,
 * **bold**, *italics*, `code`, [text](links), bare links, and [n] citations. Citations jump to reference n (``ref-n``
 * on the page), or call ``onCite`` when given. Anything else shows as plain text.
 */
export function Markdown({ text, idPrefix = 'ref', onCite, className }: {
  text: string
  idPrefix?: string
  onCite?: (n: number) => void
  className?: string
}) {
  const blocks: ReactNode[] = []
  const lines = text.split('\n')
  const inl = (s: string) => inline(s, idPrefix, onCite)
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) {
      i++
      continue
    }
    if (line.startsWith('```')) {
      const lang = line.slice(3).trim()
      const code: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) code.push(lines[i++])
      i++
      blocks.push(
        <pre key={i} className="overflow-x-auto rounded-lg border border-line bg-surface-2 px-3 py-2.5 font-mono text-[12.5px] leading-relaxed text-fg" data-lang={lang || undefined}>
          <code>{code.join('\n')}</code>
        </pre>,
      )
      continue
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      const level = heading[1].length
      const cls = level <= 2 ? 'mt-2 text-[15px] font-semibold text-fg' : 'mt-1 text-[14px] font-semibold text-fg'
      blocks.push(level <= 2 ? <h3 key={i} className={cls}>{inl(heading[2])}</h3> : <h4 key={i} className={cls}>{inl(heading[2])}</h4>)
      i++
      continue
    }
    if (/^>\s?/.test(line)) {
      const quote: string[] = []
      while (i < lines.length && /^>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^>\s?/, ''))
      blocks.push(<blockquote key={i} className="border-l-2 border-line-strong pl-3 text-fg-2 italic">{inl(quote.join(' '))}</blockquote>)
      continue
    }
    if (line.trim().startsWith('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const cells = (row: string) => row.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
      const head = cells(line)
      i += 2
      const rows: string[][] = []
      while (i < lines.length && lines[i].trim().startsWith('|')) rows.push(cells(lines[i++]))
      blocks.push(
        <div key={i} className="overflow-x-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr>{head.map((c, k) => <th key={k} className="border-b border-line-strong px-2 py-1.5 text-left font-medium text-fg">{inl(c)}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r, k) => (
                <tr key={k}>{r.map((c, j) => <td key={j} className="border-b border-line px-2 py-1.5 align-top">{inl(c)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
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
          {items.map((item, k) => <li key={k}>{inl(item)}</li>)}
        </List>,
      )
      continue
    }
    const para: string[] = []
    while (i < lines.length && lines[i].trim() && (para.length === 0 || !BLOCK_START.test(lines[i]))) {
      para.push(lines[i].trim())
      i++
    }
    blocks.push(<p key={i}>{inl(para.join(' '))}</p>)
  }
  return <div className={className ?? 'grid gap-3 text-[14px] leading-relaxed text-fg-2'}>{blocks}</div>
}

const TOKEN = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[[^\]]+\]\(https?:\/\/[^\s)]+\)|\[\d+(?:\s*,\s*\d+)*\]|https?:\/\/[^\s)]+)/g

function inline(text: string, idPrefix: string, onCite?: (n: number) => void): ReactNode {
  const parts = text.split(TOKEN)
  return parts.map((part, k) => {
    if (!part) return null
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return <code key={k} className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[12.5px] text-fg">{part.slice(1, -1)}</code>
    }
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={k} className="font-semibold text-fg">{part.slice(2, -2)}</strong>
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) return <em key={k}>{part.slice(1, -1)}</em>
    const link = /^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/.exec(part)
    if (link) return <a key={k} href={link[2]} target="_blank" rel="noopener noreferrer" className="text-accent-ink hover:underline">{link[1]}</a>
    if (/^\[\d/.test(part)) {
      const nums = part.slice(1, -1).split(',').map((n) => n.trim())
      return (
        <span key={k} className="whitespace-nowrap">
          [{nums.map((n, j) => (
            <Fragment key={n}>
              {j > 0 && ', '}
              {onCite ? (
                <button type="button" onClick={() => onCite(Number(n))} className="font-mono text-[12px] text-accent-ink hover:underline">{n}</button>
              ) : (
                <a href={`#${idPrefix}-${n}`} className="font-mono text-[12px] text-accent-ink hover:underline">{n}</a>
              )}
            </Fragment>
          ))}]
        </span>
      )
    }
    if (/^https?:\/\//.test(part)) return <a key={k} href={part} target="_blank" rel="noopener noreferrer" className="break-all text-accent-ink hover:underline">{part}</a>
    return <Fragment key={k}>{part}</Fragment>
  })
}
