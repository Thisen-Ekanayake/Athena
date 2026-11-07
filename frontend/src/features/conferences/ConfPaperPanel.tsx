import { useEffect } from 'react'
import { BookOpen, ExternalLink, FileText, GitBranch, X } from 'lucide-react'
import { motion } from 'framer-motion'
import { useConfPaper, useConfPaperItem } from '../../api/queries/conferences'
import { apiErrorMessage } from '../../api/error'
import { SaveMenu } from '../../components/items/SaveMenu'
import { usePanelStore } from '../../store/panelStore'
import { AddToProjectMenu } from '../projects/AddToProjectMenu'
import { Button, ButtonLink } from '../../ui/Button'
import { buttonClass } from '../../ui/buttonClass'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { KIND_LABEL } from './format'
import { AwardChips, PaperRow } from './parts'

const ABSTRACT_FROM: Record<string, string> = { openalex: 'OpenAlex', semantic_scholar: 'Semantic Scholar' }

/**
 * A conference paper beside the page: the Anthology's record, its citations and topic, and similar papers. Saving,
 * notes and projects work on Athena's own copy of the paper, which "Open in Athena" makes the first time.
 */
export function ConfPaperPanel({ paperId, onClose, onOpen }: { paperId: string; onClose: () => void; onOpen: (id: string) => void }) {
  const { data: p, isLoading, error } = useConfPaper(paperId)
  const asItem = useConfPaperItem()
  const openItem = usePanelStore((s) => s.open)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !e.defaultPrevented) onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const openInAthena = async () => {
    const { item_id } = p?.item_id ? { item_id: p.item_id } : await asItem.mutateAsync(paperId)
    onClose()
    openItem(item_id)
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-bg/50 xl:hidden" onClick={onClose} aria-hidden="true" />
      <motion.aside
        key={paperId}
        initial={{ x: 24, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[520px] flex-col border-l border-line bg-surface shadow-pop"
        aria-label="Conference paper"
      >
        <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
          <p className="truncate text-[12.5px] text-fg-3">{p ? p.venues.map((v) => v.name).join(' · ') + ` ${p.year}` : 'Paper'}</p>
          <div className="flex items-center gap-1">
            {p?.item_id && <SaveMenu itemId={p.item_id} />}
            {p?.item_id && <AddToProjectMenu compact membershipRef={`item:${p.item_id}`} item={{ kind: 'paper', id: p.item_id }} />}
            <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close"><X /></Button>
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {isLoading && <div className="flex justify-center py-16"><Spinner label="Loading the paper…" /></div>}
          {error && <Notice tone="error" className="m-4">{apiErrorMessage(error, 'The paper did not load.')}</Notice>}
          {p && (
            <article className="grid gap-4 px-5 py-5">
              <div className="grid gap-2">
                <h2 className="text-[17px] font-semibold leading-snug text-fg">{p.title}</h2>
                <p className="text-[13px] text-fg-2">{p.authors.join(', ')}</p>
                <div className="flex flex-wrap items-center gap-1.5">
                  {p.kind && <Chip>{KIND_LABEL[p.kind]}</Chip>}
                  {p.topic && <Chip>{p.topic.name}</Chip>}
                  <AwardChips awards={p.awards} />
                </div>
              </div>
              <dl className="grid grid-cols-2 gap-3 rounded-xl border border-line px-4 py-3 text-[12.5px]">
                <div>
                  <dt className="text-fg-3">Citations</dt>
                  <dd className="text-[15px] font-medium text-fg">{p.citation_count?.toLocaleString() ?? 'Not counted yet'}</dd>
                </div>
                <div>
                  <dt className="text-fg-3">In</dt>
                  <dd className="text-fg-2" title={p.volume.title ?? undefined}>{p.volume.id}</dd>
                </div>
              </dl>
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" size="sm" onClick={openInAthena} disabled={asItem.isPending}>
                  {asItem.isPending ? <Spinner className="h-3.5 w-3.5" /> : <BookOpen />} Open in Athena
                </Button>
                <a className={buttonClass('secondary', 'sm')} href={p.pdf_url} target="_blank" rel="noreferrer"><FileText /> PDF</a>
                <a className={buttonClass('secondary', 'sm')} href={p.url} target="_blank" rel="noreferrer"><ExternalLink /> Anthology</a>
                <ButtonLink to={`/evolution?q=${encodeURIComponent(p.title)}`} variant="ghost" size="sm" title="Find or build a research map of this paper's field">
                  <GitBranch /> Map its field
                </ButtonLink>
              </div>
              {asItem.error && <Notice tone="error">{apiErrorMessage(asItem.error, 'Athena could not keep the paper.')}</Notice>}
              {!p.item_id && <p className="-mt-2 text-[12px] text-fg-3">Open it in Athena to save it to a list, take notes, ask about it or add it to a project.</p>}
              <section className="grid gap-1.5">
                <h3 className="text-[12px] font-medium uppercase tracking-wide text-fg-3">Abstract</h3>
                {p.abstract
                  ? <p className="text-[13.5px] leading-relaxed text-fg-2">{p.abstract}</p>
                  : <p className="text-[13px] text-fg-3">The Anthology has no abstract for this paper, and neither OpenAlex nor Semantic Scholar had one.</p>}
                {p.abstract_from && ABSTRACT_FROM[p.abstract_from] && (
                  <p className="text-[11.5px] text-fg-3">Abstract from {ABSTRACT_FROM[p.abstract_from]}: the Anthology has none for this paper.</p>
                )}
              </section>
              {p.similar.length > 0 && (
                <section className="grid gap-1">
                  <h3 className="text-[12px] font-medium uppercase tracking-wide text-fg-3">Similar papers in the ACL family</h3>
                  <ul className="-mx-4">{p.similar.map((s) => <PaperRow key={s.id} paper={s} onOpen={onOpen} />)}</ul>
                </section>
              )}
            </article>
          )}
        </div>
      </motion.aside>
    </>
  )
}
