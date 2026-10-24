import { useId } from 'react'

/**
 * A small superscript "i" after a label; hovering or focusing it shows a one-sentence explanation.
 * The note opens down and to the right of the "i", and is drawn in place, not in a portal, so it also
 * shows inside a full-screen element.
 */
export function InfoTip({ text, label }: { text: string; label: string }) {
  const id = useId()
  return (
    <span className="group relative -top-1.5 ml-0.5 inline-flex">
      <button
        type="button"
        aria-label={`What "${label}" means`}
        aria-describedby={id}
        className="inline-flex h-3 w-3 items-center justify-center rounded-full border border-line-strong font-serif text-[8px] leading-none text-fg-3 italic transition-colors hover:border-fg-3 hover:text-fg focus-visible:border-accent focus-visible:text-fg focus-visible:outline-none"
      >
        i
      </button>
      <span
        id={id}
        role="tooltip"
        className="pointer-events-none invisible absolute top-full -left-2 z-20 mt-1.5 w-max max-w-60 rounded-md border border-line-strong bg-surface-2 px-2.5 py-1.5 text-[12px] leading-snug text-fg-2 opacity-0 shadow-lg transition-opacity group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100"
      >
        {text}
      </span>
    </span>
  )
}
