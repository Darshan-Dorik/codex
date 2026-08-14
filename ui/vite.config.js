import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Pinned, and strict. Vite's default is 5173, but when 5173 is
    // busy it silently falls back to 5174 — which is the backend's
    // port. Vite binds IPv6 and the Python server binds IPv4, so both
    // "succeed" and the app's fetch('http://localhost:5174/state')
    // lands on Vite and 404s. strictPort turns that into a loud
    // failure instead of a dashboard that loads but never connects.
    port: 5173,
    strictPort: true,
  },
})
