# Athena's UI

How the React app in `frontend/` is laid out. It covers what is on each page and where the code lives, so a
change starts in the right file. For running it, see `frontend/README.md`.

## Look

One dark base and two accents, set in `frontend/src/index.css`:

- **Gold** (the default): warm bronze on near-black (`--accent: #d6ae5f`).
- **Indigo**: cool silver and violet (`--accent: #8e8ef6`).

`<html data-accent="gold|indigo">` picks the accent. The sidebar's swatches and Settings → Appearance set it
(`store/appStore.ts`, saved in the browser). Every colour is a CSS variable (`--bg`, `--surface`, `--surface-2`,
`--surface-3`, `--line`, `--fg`, `--fg-2`, `--fg-3`, `--accent`, `--accent-soft`, ...), and Tailwind reads them as
`bg-surface`, `text-fg-2`, `border-line`, `text-accent` and so on. Use these instead of fixed colours, so that
switching the accent restyles everything. Status colours (`--good`, `--warn`, `--bad`) are the same in both looks.
The map and the 3D scenes have their own variables (`--map-bg`, `--metal`, `--star`, ...).

Fonts: Geist for text, Geist Mono for numbers and code, GFS Didot for the few mythic headings. The animated
astrolabe (`features/astrolabe/`) appears only on Home and in the places where you ask the model a question
(a paper, a map, a review).

## Shell

`components/layout/AppShell.tsx` wraps every signed-in page:

- **Sidebar** (`Sidebar.tsx`): Home, Feed, Rising, Clusters, Evolution and Library; the accent swatches;
  Settings; the account and log-out button; and the **sync panel** (`SyncPanel.tsx`), which shows a running
  sync's progress, ETA and log. Admins can start a sync there. On narrow screens the sidebar becomes a drawer.
- **Top bar** (`TopBar.tsx`): the menu button on mobile, the search box (it opens the command palette) and the
  inbox bell (`InboxBell.tsx`).
- **⌘K / Ctrl+K** opens the command palette (`components/command/CommandPalette.tsx`): one search for pages, maps,
  clusters and papers, plus the AI actions (see all results, write a literature review).
- **Paper panel** (`components/paper/PaperPanel.tsx`): clicking any item opens it in a side panel with its
  summary, score breakdown, Q&A, notes and its place in a research map. "Expand" opens the full page
  (`/items/:id`). `store/panelStore.ts` holds the open item.

Pages outside the shell (login, setup, password change, the setup guide and shared maps) use the frame in
`pages/AuthPages.tsx`. `RequireAuth` there sends everyone else to setup, login or a password change, and sends
new accounts to the guide first.

## Pages

| Route | Page | What it shows |
|---|---|---|
| `/` | `pages/HomePage.tsx` | What is new, what is rising, and where your research maps stand |
| `/feed`, `/sources/:id` | `pages/FeedPage.tsx` | Everything from your sources (or one source), sorted by Relevance, Newest or For you, filtered by kind (papers, lab blogs, community) and time |
| `/rising` | `pages/RisingPage.tsx` | Feed papers gaining citations fastest (7- and 30-day gains). `/trending` redirects here |
| `/clusters`, `/clusters/:id` | `pages/ClustersPage.tsx`, `ClusterPage.tsx` | Themes found by grouping similar items |
| `/evolution` | `features/evolution/EvolutionPage.tsx` | The research maps, and a proposal panel for building a new one from a search |
| `/evolution/:slug` | same | One map, with tabs: Lineage map, Reading path, Open problems, Ask, People, Links, Changes. The tab and the selected paper are in the URL |
| `/evolution/ideas` | `features/evolution/IdeaCheckPage.tsx` | Check an idea or abstract against every map |
| `/library`, `/library/:tab` | `pages/LibraryPage.tsx` | Your lists, notes and highlights, what you have read, and your literature reviews |
| `/reviews/:id` | `pages/ReviewPage.tsx` | One literature review, full width |
| `/inbox` | `pages/InboxPage.tsx` | Map updates, follows and digests from the last 60 days |
| `/search` | `pages/SearchPage.tsx` | One search over your library (and optionally Semantic Scholar), the matching map and a literature review |
| `/items/:id` | `pages/PaperPage.tsx` | One item as a full page |
| `/settings/:tab` | `pages/SettingsPage.tsx` | Everyone: Account, Notifications, Personalisation, Usage, Appearance. Admins also get Sources, Models and keys, Users, Sharing, Scoring, Clusters, Health and Sync log |
| `/welcome` | `features/onboarding/WelcomePage.tsx` | The setup guide for new accounts |
| `/share/:token` | `features/evolution/SharedMapPage.tsx` | A read-only map behind a share link, with no account needed |
| `/login`, `/setup`, `/change-password` | `pages/AuthPages.tsx` | Sign in; create the first (admin) account; replace a temporary password |

The map pages, the idea check, the setup guide and shared maps load lazily, so the graph library only
downloads when a map opens.

## Code layout

```
frontend/src/
  App.tsx            routes
  api/               axios client (client.ts, calls /api/v1), error messages, TanStack Query hooks (queries/)
  components/        the shell (layout/), item rows and actions (items/), the paper panel (paper/), ⌘K (command/)
  features/          one folder per feature: evolution, search, reviews, reading, inbox, momentum,
                     personalisation, settings, usage, onboarding, astrolabe
  pages/             one file per top-level route
  store/             Zustand stores: accent, open panel and palette, Q&A conversations, sync dialog
  ui/                small building blocks: Button, Card, Chip, Segmented, PageHeader, EmptyState, Spinner, ...
  test/utils.tsx     mockApi (a fake API under the app's axios client) and renderWithProviders
```

Server state lives in TanStack Query, and the only state kept in the browser is the accent and a few
remembered choices (such as the feed's last sort). Each feature's hooks sit next to it
(`features/evolution/api/`, one file per part of a map; `features/search/api.ts`) or in `api/queries/` (feed,
score, search, clusters, ...). Tests sit next to the code as `*.test.tsx`.
