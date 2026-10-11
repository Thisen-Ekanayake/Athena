import { cn } from './cn'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'ai'
export type ButtonSize = 'sm' | 'md' | 'icon' | 'icon-sm'

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-primary text-on-primary hover:opacity-90',
  secondary: 'border border-line bg-surface text-fg hover:border-line-strong hover:bg-surface-2',
  ghost: 'text-fg-2 hover:bg-surface-2 hover:text-fg',
  // Starts an AI action: looks like a secondary button with an accent icon.
  ai: 'border border-line bg-surface text-fg hover:border-accent-line [&_svg]:text-accent',
}

const SIZES: Record<ButtonSize, string> = {
  sm: 'h-7 gap-1.5 px-2.5 text-[12.5px] [&_svg]:h-3.5 [&_svg]:w-3.5',
  md: 'h-8 gap-2 px-3 text-[13px] [&_svg]:h-4 [&_svg]:w-4',
  icon: 'h-8 w-8 [&_svg]:h-4 [&_svg]:w-4',
  'icon-sm': 'h-7 w-7 [&_svg]:h-3.5 [&_svg]:w-3.5',
}

export function buttonClass(variant: ButtonVariant = 'secondary', size: ButtonSize = 'md', className?: string) {
  return cn(
    'inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-lg font-medium transition-colors',
    'disabled:pointer-events-none disabled:opacity-50',
    VARIANTS[variant],
    SIZES[size],
    className,
  )
}
