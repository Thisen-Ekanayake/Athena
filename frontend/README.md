# Athena frontend

The React app for Athena: React 19, TypeScript and Vite, with TanStack Query for server state, Zustand for the
little state kept in the browser, and Tailwind CSS 4. Pages, layout and design tokens are described in
[`docs/ui.md`](../docs/ui.md).

## Commands

Node 22.12 or newer (Vitest and jsdom need it; the image builds on Node 24).

```bash
npm install
npm run dev          # http://localhost:5173
npm run lint
npm test             # Vitest + React Testing Library in jsdom; npm run test:watch re-runs on save
npm run build        # type-checks (tsc -b), then builds into dist/
```

## The API

The app calls the API on its own origin, at `/api/v1`. In development Vite's proxy (`vite.config.ts`) passes it
to uvicorn on `127.0.0.1:8000`. In the image, nginx (`nginx.conf`) passes it to the API service. Set
`VITE_API_URL` at build time to call an API elsewhere; that API then needs the app's origin in `CORS_ORIGINS`.
Every page except login, setup and shared maps needs a session: the API sets an httpOnly cookie when you log in.

## Layout

- `src/App.tsx`: the routes
- `src/pages/`: one file per top-level page
- `src/features/`: one folder per feature (evolution, search, reviews, reading, inbox, momentum, settings, ...)
- `src/components/`: the shell, item rows, the paper panel and the command palette
- `src/ui/`: small shared building blocks
- `src/api/`: the axios client and the query hooks
- `src/test/utils.tsx`: `mockApi` fakes the API under the app's axios client, and `renderWithProviders`
  renders with a query cache and a router. Tests sit next to the code as `*.test.tsx`.
