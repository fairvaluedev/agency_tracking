import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Proxying /api to the Frappe backend makes every request same-origin from the browser's
// point of view — avoids CORS and cross-site cookie (SameSite) issues entirely, the standard
// pattern for a framework-agnostic SPA sitting in front of Frappe's session-cookie auth
// (Part F: "session-cookie for everyone... simplest for low-technical-literacy users").
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
