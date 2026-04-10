import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/** Port UI (dev + preview). Surcharge : CYBERALPHA_WEB_PORT=4000 npm run dev */
const WEB_PORT = (() => {
  const n = parseInt(process.env.CYBERALPHA_WEB_PORT ?? '3780', 10)
  return n > 0 && n < 65536 ? n : 3780
})()

export default defineConfig({
  plugins: [react()],
  server: {
    // Obligatoire pour accès depuis le téléphone / autre machine (sinon 127.0.0.1 seulement)
    host: '0.0.0.0',
    port: WEB_PORT,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        rewrite: (path) => path.replace(/^\/api/, ''),
        timeout: 600_000,
      },
    },
  },
  preview: {
    port: WEB_PORT,
    host: '0.0.0.0',
  },
})
