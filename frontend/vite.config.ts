/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  // The app calls the API on its own origin (/api/v1); in development Vite passes those calls to uvicorn,
  // as nginx does in the frontend image. 127.0.0.1, not localhost: uvicorn listens on IPv4 only.
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  // `npm test`: components render in jsdom against a faked API (src/test/utils.tsx).
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: false,
  },
})
