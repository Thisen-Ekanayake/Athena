# Athena UI Documentation

> **Design Direction**: Glassmorphism · Deep Oxford Indigo · Futuristic Research Intelligence

Athena's frontend is a high-performance, responsive research intelligence interface designed to aggregate and surface key AI trends, research papers, and industrial news. The interface embodies a **deep-space glassmorphism** aesthetic — layered frosted glass panels floating above a rich, dark indigo cosmos, creating a sense of depth, clarity, and quiet authority.

---

## 🛠 Tech Stack

| Layer | Technology |
|---|---|
| **Core Framework** | React 19 |
| **Build Tool** | Vite 8 |
| **Language** | TypeScript |
| **Styling** | Tailwind CSS 4 + Custom CSS Variables |
| **State Management** | Zustand |
| **Data Fetching** | TanStack Query (React Query) |
| **Animation** | Motion (Framer Motion v11+) |
| **Icons** | Lucide React |
| **Routing** | React Router DOM 7 |
| **Fonts** | Syne (display) + DM Sans (body) |

---

## 🎨 Design System

### Philosophy

Athena's visual language is built on **layered translucency** — every surface is a pane of frosted glass hovering above a deep indigo void. The effect communicates intelligence without loudness: information floats, breathes, and organises itself in space rather than sitting flat on a page.

Three principles govern every design decision:

1. **Depth over flatness** — surfaces have z-axis presence via backdrop blur, layered shadows, and subtle border luminance.
2. **Restraint over decoration** — motion and colour are purposeful signals, never noise.
3. **Legibility always wins** — contrast ratios meet WCAG AA minimum across all glass surfaces.

---

### Colour Palette

The palette anchors on **Oxford Blue** (`#0a0f2c`) as the deep void beneath all surfaces, with a cool indigo-to-slate gradient atmosphere layered on top. Accent colours are drawn from bioluminescent deep-sea tones — blue-violet, cerulean, and soft aqua — to suggest intelligence radiating from within.

#### Core Tokens

```css
:root {
  /* ── Void & Atmosphere ── */
  --color-void:        #060917;   /* deepest background layer          */
  --color-abyss:       #0a0f2c;   /* Oxford Blue — base atmosphere      */
  --color-deep:        #0d1540;   /* card backing / secondary surfaces  */
  --color-surface:     #111a4a;   /* primary glass backing              */
  --color-lift:        #1a2560;   /* elevated / hover surface           */

  /* ── Glass Surfaces ── */
  --glass-fill:        rgba(17, 26, 74, 0.45);
  --glass-fill-hover:  rgba(26, 37, 96, 0.60);
  --glass-fill-active: rgba(26, 37, 96, 0.80);
  --glass-blur:        16px;
  --glass-blur-heavy:  28px;

  /* ── Borders (luminous edge) ── */
  --border-subtle:     rgba(99, 122, 255, 0.12);
  --border-default:    rgba(99, 122, 255, 0.22);
  --border-glow:       rgba(99, 122, 255, 0.45);

  /* ── Accent Spectrum ── */
  --accent-primary:    #4c5fff;   /* Oxford Indigo — primary CTA        */
  --accent-secondary:  #2e7fff;   /* Cerulean — links, highlights       */
  --accent-tertiary:   #38c5d4;   /* Aqua — positive signals, tags      */
  --accent-warning:    #e0a94b;   /* Amber — mid-tier signals           */
  --accent-critical:   #e05a6b;   /* Rose — alerts, low-score signals   */
  --accent-success:    #3dd68c;   /* Emerald — high-score / confirmed   */

  /* ── Glow (ambient light leaks) ── */
  --glow-primary:      0 0 32px rgba(76, 95, 255, 0.30);
  --glow-secondary:    0 0 24px rgba(56, 197, 212, 0.20);
  --glow-card:         0 8px 48px rgba(6, 9, 23, 0.70);

  /* ── Typography ── */
  --font-display:      'Syne', sans-serif;       /* headings, labels        */
  --font-body:         'DM Sans', sans-serif;    /* body, UI text           */
  --font-mono:         'JetBrains Mono', monospace; /* scores, IDs, code   */

  /* ── Text Scale ── */
  --text-primary:      rgba(235, 238, 255, 0.95);
  --text-secondary:    rgba(180, 190, 235, 0.75);
  --text-muted:        rgba(120, 135, 185, 0.55);
  --text-ghost:        rgba(90, 105, 160, 0.40);

  /* ── Radius ── */
  --radius-sm:   8px;
  --radius-md:   14px;
  --radius-lg:   20px;
  --radius-xl:   28px;
  --radius-pill: 999px;

  /* ── Motion ── */
  --ease-glass:  cubic-bezier(0.16, 1, 0.3, 1);
  --ease-snap:   cubic-bezier(0.34, 1.56, 0.64, 1);
  --dur-fast:    120ms;
  --dur-mid:     240ms;
  --dur-slow:    480ms;
}
```

---

### Glass Surface System

Every surface in Athena is built from a consistent glass recipe. The system has four tiers:

| Tier | Use Case | Blur | Fill Opacity | Border |
|---|---|---|---|---|
| **Base Glass** | Primary cards, panels | `16px` | `45%` | `--border-subtle` |
| **Float Glass** | Hover states, modals | `20px` | `60%` | `--border-default` |
| **Opaque Glass** | Active / focused panels | `28px` | `80%` | `--border-glow` |
| **Void Glass** | Background layers, insets | `8px` | `20%` | `none` |

```css
/* Base Glass Utility */
.glass {
  background:     var(--glass-fill);
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
  border:         1px solid var(--border-subtle);
  border-radius:  var(--radius-lg);
  box-shadow:     var(--glow-card),
                  inset 0 1px 0 rgba(255,255,255,0.06);
  transition:     background var(--dur-mid) var(--ease-glass),
                  border-color var(--dur-mid) var(--ease-glass),
                  box-shadow var(--dur-mid) var(--ease-glass);
}

.glass:hover {
  background:     var(--glass-fill-hover);
  border-color:   var(--border-default);
  box-shadow:     var(--glow-card), var(--glow-primary),
                  inset 0 1px 0 rgba(255,255,255,0.09);
}
```

---

### Background Atmosphere

The global background is a layered gradient cosmos — **not** a solid colour — with a slow-drifting radial mesh that gives the impression of ambient light sources deep in space.

```css
body {
  background-color: var(--color-void);
  background-image:
    /* Primary orb — top-left, Oxford Indigo */
    radial-gradient(ellipse 80% 60% at 15% 10%,
      rgba(76, 95, 255, 0.18) 0%, transparent 65%),
    /* Secondary orb — bottom-right, Cerulean */
    radial-gradient(ellipse 70% 50% at 85% 90%,
      rgba(46, 127, 255, 0.14) 0%, transparent 60%),
    /* Tertiary orb — centre, Aqua whisper */
    radial-gradient(ellipse 50% 40% at 50% 50%,
      rgba(56, 197, 212, 0.06) 0%, transparent 70%);
  background-attachment: fixed;
}
```

A subtle **noise texture overlay** (`opacity: 0.025`) adds surface grain, preventing the dark background from appearing flat on high-DPI displays.

---

### Typography

| Role | Font | Weight | Size Token |
|---|---|---|---|
| **Display / Hero** | Syne | 700–800 | `2.5rem+` |
| **Section Heading** | Syne | 600 | `1.25rem` |
| **UI Label** | Syne | 500 | `0.8rem` (tracked +0.08em) |
| **Body Text** | DM Sans | 400 | `0.9rem` |
| **Secondary Text** | DM Sans | 400 | `0.8rem` |
| **Score / ID / Code** | JetBrains Mono | 500 | `0.85rem` |

Font loading via Google Fonts:
```html
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@500;600;700;800&family=DM+Sans:wght@300;400;500&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
```

---

### Iconography

Lucide React icons are used throughout at consistent sizing:

| Context | Size | Colour |
|---|---|---|
| Sidebar navigation | `18px` | `--text-secondary` |
| Active nav item | `18px` | `--accent-primary` (+ `--glow-primary`) |
| Card actions | `15px` | `--text-muted` |
| Status indicators | `13px` | Contextual accent |

Icons on active/hover states receive a subtle drop-shadow glow matching the nearest accent colour.

---

## 🏗 Architecture & Layout

The application follows a standard SPA architecture with a carefully considered layered layout system.

### Global Layout (`components/Layout.tsx`)

```
┌─────────────────────────────────────────────────────────────────┐
│  VOID BACKGROUND (fixed, layered gradient mesh)                 │
│  ┌───────────────┐  ┌───────────────────────┐  ┌────────────┐  │
│  │  LEFT SIDEBAR │  │     MAIN CONTENT       │  │  RELATED   │  │
│  │  glass panel  │  │   Outlet / Router      │  │  SIDEBAR   │  │
│  │  w-64 sticky  │  │   scrollable region    │  │  glass     │  │
│  │               │  │                        │  │  w-72      │  │
│  └───────────────┘  └───────────────────────┘  └────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

#### Left Sidebar (`components/Sidebar.tsx`)

A **tall frosted glass panel** docked to the left edge. It does not have a hard background fill — it is translucent against the animated background.

- **Logo mark**: Wordmark in Syne 700 with a small luminous indigo glyph icon. A faint horizontal rule with `--border-subtle` separates it from nav links.
- **Global Search** (`components/SearchInput.tsx`): A pill-shaped glass input with `backdrop-filter: blur(20px)`. A faint pulsing ring animation plays on focus.
- **Primary Navigation**: Icon + label links. Active state: label shifts to `--text-primary`, icon receives `--accent-primary` colour and a soft box-shadow glow. Inactive links fade to `--text-muted`.
- **Section Labels**: `DISCOVER`, `MANAGE` etc. in Syne 500 at `0.68rem`, tracked widely, coloured `--text-ghost`.
- **Bottom area**: User avatar, connection status pill, settings shortcut — all glassed.

#### Mobile Header

On viewports `< 768px`, the sidebar collapses. A sticky frosted header bar appears with:
- Left: Athena logo
- Right: Hamburger icon → slides in a full-height drawer (glass, `--glass-fill-active`)

#### Related Sidebar (`components/RelatedSidebar.tsx`)

A contextual right panel that fades in when a user focuses on a feed card or enters a cluster view. It displays:
- "Related to" label
- 3–5 related item cards (compact glass cards)
- A subtle slide-in animation from the right (`translateX(16px) → 0`, opacity fade)

---

## 📄 Pages

### 1. Feed (`pages/FeedPage.tsx`)

The primary landing page. A ranked, filterable stream of research cards rendered in a single-column layout with generous vertical spacing between cards.

**Layout**: Full-width content area with `max-width: 760px`, centred.

**Filter Bar**: Horizontally scrollable pill-button row at the top of the feed. Active filter pills have:
- `background: var(--glass-fill-hover)`
- `border-color: var(--border-glow)`
- Left accent bar: `3px solid var(--accent-primary)`

**Infinite Scroll**: An `IntersectionObserver` sentinel at the bottom of the list triggers the next page load. A subtle shimmer skeleton (glass-tinted, animated gradient sweep) replaces loading spinners.

---

### 2. Trending (`pages/TrendingPage.tsx`)

A higher-energy layout highlighting rapidly rising content. Differentiators from the Feed:

- **Hero Card**: The top-trending item is displayed at full width with an expanded layout — larger score ring, extended summary, citation velocity chart (sparkline).
- **Velocity Badge**: A small animated badge (`↑ +142 citations / 24h`) in `--accent-tertiary` appears on qualifying cards.
- **Background shift**: The atmosphere orbs subtly shift hue toward cerulean on this page to signal elevated energy.

---

### 3. Topics / Clusters (`pages/ClusterBrowserPage.tsx`)

A spatial, grid-based bird's-eye view of semantic research clusters.

**Layout**: A fluid CSS grid (`auto-fill`, `minmax(220px, 1fr)`) of **Cluster Tiles**.

**Cluster Tile Design**:
- Glass card with a unique per-cluster tinted top border (`border-top: 2px solid <cluster-colour>`)
- Cluster name in Syne 600
- Item count badge (pill, `--void-glass`)
- Top-3 keyword tags in `--accent-tertiary`
- Subtle hover: card lifts (`translateY(-4px)`), border glow intensifies

Clicking a tile navigates to `ClusterViewPage.tsx`, which uses the same feed layout but scoped to that cluster's items, with the cluster name displayed in a large Syne 800 hero heading above the list.

---

### 4. Search (`pages/SearchResultsPage.tsx`)

Activated from the sidebar search input. Results stream in with staggered fade-up animations (`animation-delay: n * 60ms`).

- **Query echo**: The search term is displayed prominently above results in Syne 600 with a `--accent-secondary` highlight on the matched term.
- **Result type chips**: `Paper`, `Blog`, `News` — pill labels using `--glass-fill` with type-specific accent colours.
- **Empty state**: A centred glass card with a faint constellation SVG illustration and a DM Sans body prompt to refine the search.

---

### 5. Settings (`pages/SettingsPage.tsx`)

A structured preferences interface divided into tabbed sections.

**Tab Bar**: Horizontal glass pill selector at the top. Active tab: `--glass-fill-active`, `--border-glow`.

**Sections**:
- **Preferences**: Toggle switches (custom glass toggle component), dropdown selectors
- **Sources**: Checkbox list of ingestion sources with status badges
- **Background Tasks**: A live-updating task list with status indicators (pulsing dot for in-progress, checkmark for complete)
- **Appearance**: Reserved for future theme customisation controls

**Form Elements**: All inputs use the base glass recipe with `--border-subtle` at rest, `--border-glow` on focus, and a `box-shadow: var(--glow-primary)` focus ring.

---

## 🧩 Core Components

### Feed Card (`components/FeedCard.tsx`)

The atomic unit of information display. Every card is a **Base Glass** surface.

```
┌─────────────────────────────────────────────────────────┐  ← glass panel
│  [SCORE RING]  Title in Syne 600                        │
│                Source · Date · Type Chip                │
│  ─────────────────────────────────────────────────      │
│  AI Summary (DM Sans, --text-secondary, 3-line clamp)   │
│  ─────────────────────────────────────────────────      │
│  ▸ Key Takeaway 1                                       │
│  ▸ Key Takeaway 2   [collapsed by default]              │
│  ─────────────────────────────────────────────────      │
│  [Ask AI ✦]  [Bookmark]  [Open ↗]        [···]         │
└─────────────────────────────────────────────────────────┘
```

**Hover behaviour**: Card transitions to Float Glass tier, a faint `--glow-primary` appears, and the score ring border brightens.

**Card entrance animation**: Cards animate in with `opacity: 0 → 1` + `translateY(12px → 0)` over `480ms var(--ease-glass)`, staggered by index.

---

### Score Ring (`components/ScoreRing.tsx`)

A circular SVG progress ring rendered using `stroke-dasharray` / `stroke-dashoffset` technique.

| Score Range | Ring Colour | Label Colour | Glow |
|---|---|---|---|
| **80 – 100** | `--accent-success` | `--accent-success` | `--glow-secondary` (green tint) |
| **50 – 79** | `--accent-warning` | `--accent-warning` | amber tint |
| **0 – 49** | `--accent-critical` | `--accent-critical` | rose tint |

The ring **animates on card mount**: stroke draws from 0 to final value over `600ms var(--ease-glass)` with a `120ms` entrance delay.

The score numeral inside the ring uses **JetBrains Mono 500**.

---

### Score Tooltip (`components/ScoreTooltip.tsx`)

Triggered on hover of the Score Ring. Renders as a **Float Glass** popover above the card with:

- Title: "Relevance Breakdown" in Syne 600
- Horizontal bar chart for each signal: Recency, Citation Velocity, Source Weight, Semantic Match
- Bars use `--accent-primary` fill on a `--void-glass` track
- Subtle appear animation: `scale(0.95) → 1` + fade, origin bottom-left

---

### Q&A Panel (`components/QAPanel.tsx`)

A slide-in panel anchored to the right edge of the viewport, overlapping the Related Sidebar when active.

- **Trigger**: "Ask AI ✦" button on any Feed Card
- **Panel surface**: **Opaque Glass** tier (`backdrop-filter: blur(28px)`, `80%` fill)
- **Header**: Card title (truncated) + "Close ✕" in top-right
- **Input area**: Bottom-anchored glass textarea with send button; send icon glows `--accent-primary` on hover
- **Response stream**: Assistant responses stream in token by token with a blinking cursor (JetBrains Mono)
- **Entrance**: Slides in from right (`translateX(100%) → 0`) over `360ms var(--ease-glass)`

---

### Search Input (`components/SearchInput.tsx`)

A persistent pill-shaped input in the left sidebar.

- At rest: `--glass-fill`, `--border-subtle`, magnifier icon `--text-muted`
- On focus: `--glass-fill-hover`, `--border-glow`, `box-shadow: var(--glow-primary)`, icon shifts to `--accent-primary`
- Keyboard shortcut hint: `⌘K` badge renders inside the input at rest, disappears on focus
- Semantic search results appear in a **Float Glass** dropdown below, max 6 results, each with an icon indicating result type

---

## 📱 Responsive Behaviour

| Breakpoint | Layout |
|---|---|
| `< 768px` (Mobile) | Single column; sidebar hidden; top header + drawer nav; Related Sidebar hidden |
| `768px – 1100px` (Tablet) | Left sidebar visible, condensed (icons only, no labels); Related Sidebar hidden |
| `1100px – 1400px` (Desktop) | Full left sidebar with labels; Related Sidebar hidden unless explicitly opened |
| `> 1400px` (Wide) | All three columns visible simultaneously |

Glass blur values are **reduced by 50%** on mobile (`prefers-reduced-motion`) to preserve performance on lower-end devices. The full animation suite is conditionally disabled via:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## ✨ Motion & Animation Principles

All motion in Athena follows three rules:

1. **Purposeful** — every animation communicates state change or hierarchy. Nothing animates arbitrarily.
2. **Springy, not bouncy** — `var(--ease-glass)` (`cubic-bezier(0.16, 1, 0.3, 1)`) is the default. It decelerates smoothly into rest, suggesting physical weight without cartoonish bounce.
3. **Fast in, slow out** — entrances complete in `< 500ms`. Exits complete in `< 250ms`.

### Key Animation Catalogue

| Interaction | Animation | Duration |
|---|---|---|
| Page load / route change | Cards stagger fade-up | `480ms`, `60ms` stagger |
| Card hover | Float lift + glow | `240ms` |
| Card exit (dismiss) | Fade + collapse height | `240ms` |
| Score ring draw | Stroke dashoffset | `600ms` + `120ms` delay |
| QA Panel open/close | Slide from right | `360ms` / `220ms` |
| Related Sidebar appear | Slide from right + fade | `300ms` |
| Tooltip appear | Scale + fade | `180ms` |
| Search dropdown appear | Height expand + fade | `200ms` |
| Cluster tile hover | translateY(-4px) | `240ms` |

---

## 🔮 Design Tokens Summary

```
Backgrounds:  void (#060917) → abyss (#0a0f2c) → deep (#0d1540) → surface (#111a4a) → lift (#1a2560)
Accents:      primary (#4c5fff) · secondary (#2e7fff) · tertiary (#38c5d4)
Signals:      success (#3dd68c) · warning (#e0a94b) · critical (#e05a6b)
Glass:        fill 45%→80% · blur 8px→28px · border rgba(99,122,255, 0.12→0.45)
Fonts:        Syne (display) · DM Sans (body) · JetBrains Mono (data)
Motion:       ease-glass (0.16,1,0.3,1) · ease-snap (0.34,1.56,0.64,1)
```
