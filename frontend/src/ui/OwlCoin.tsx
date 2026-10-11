import { cn } from './cn'

/**
 * Athena's mark: the owl from Athenian silver coins. The full emblem adds the olive sprig,
 * the beaded rim and the letters ΑΘΕ; small sizes drop them so the owl stays readable.
 */
export function OwlCoin({ size = 24, full = false, className }: { size?: number; full?: boolean; className?: string }) {
  const owl = (
    <>
      <path className="fill-accent" d="M34 27 L36 16.5 L42.5 23.5 Z" />
      <path className="fill-accent" d="M58 27 L56 16.5 L49.5 23.5 Z" />
      <ellipse className="fill-accent" cx="46" cy="58" rx="15" ry="20" />
      <circle className="fill-accent" cx="46" cy="33" r="13" />
      <circle className="fill-surface" cx="40.5" cy="32" r="5.2" />
      <circle className="fill-surface" cx="51.5" cy="32" r="5.2" />
      <circle className="fill-accent" cx="40.5" cy="32" r="2.4" />
      <circle className="fill-accent" cx="51.5" cy="32" r="2.4" />
      <path className="fill-surface" d="M44 37.5 L48 37.5 L46 42 Z" />
      <path className="fill-none stroke-surface" strokeWidth={1.6} strokeLinecap="round" d="M35.5 52 q5 10 3 21 M56.5 52 q-5 10 -3 21" />
      <path
        className="fill-none stroke-surface"
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M42.5 55 l3.5 2.6 l3.5 -2.6 M42.5 61.5 l3.5 2.6 l3.5 -2.6 M42.5 68 l3.5 2.6 l3.5 -2.6"
      />
      <path className="fill-none stroke-accent" strokeWidth={1.8} strokeLinecap="round" d="M41.5 78 v4 M50.5 78 v4" />
    </>
  )
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" aria-hidden="true" className={cn('shrink-0', className)}>
      <circle className="fill-surface stroke-accent" cx="50" cy="50" r="47.5" strokeWidth={full ? 1.5 : 3} />
      <circle className="fill-accent-soft" cx="50" cy="50" r="47.5" />
      {full ? (
        <>
          <circle className="fill-none stroke-accent" cx="50" cy="50" r="42" strokeWidth={1.8} strokeLinecap="round" strokeDasharray="0 1" pathLength={64} />
          <path className="fill-none stroke-accent" strokeWidth={1.4} strokeLinecap="round" d="M15.5 47 C 18 38, 22 31, 29.5 25" />
          <ellipse className="fill-accent" cx="16.4" cy="38.5" rx="4.4" ry="1.7" transform="rotate(-62 16.4 38.5)" />
          <ellipse className="fill-accent" cx="24.6" cy="34" rx="4.4" ry="1.7" transform="rotate(-18 24.6 34)" />
          <ellipse className="fill-accent" cx="21.2" cy="27.6" rx="4.4" ry="1.7" transform="rotate(-70 21.2 27.6)" />
          <circle className="fill-accent" cx="28.6" cy="29.8" r="1.8" />
          {['Α', 'Θ', 'Ε'].map((letter, i) => (
            <text key={letter} className="fill-accent font-myth" x="74" y={44 + i * 12} fontSize="11" textAnchor="middle">{letter}</text>
          ))}
          {owl}
        </>
      ) : (
        <g transform="translate(50 51) scale(1.22) translate(-46 -49)">{owl}</g>
      )}
    </svg>
  )
}
