import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Прокси /api к backend-сервису внутри docker-compose сети
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: {
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/admin': {
        target: 'http://backend:8000',
        changeOrigin: true,
        secure: false,
      },
      '/events': {
        target: 'http://backend:8000',
        changeOrigin: true,
        secure: false,
      },
      '/calendar': {
        target: 'http://backend:8000',
        changeOrigin: true,
        secure: false,
        // SPA-ссылки вида /calendar/m15/event/:id — это React, не API GET /calendar
        bypass(req) {
          if (req.url?.startsWith('/calendar/m15')) {
            return '/index.html'
          }
        },
      },
      '/auth': {
        target: 'http://backend:8000',
        changeOrigin: true,
        secure: false,
      },
      '/owner': {
        target: 'http://backend:8000',
        changeOrigin: true,
        secure: false,
      },
      '/homework-completion': {
        target: 'http://backend:8000',
        changeOrigin: true,
        secure: false,
      },
      '/files': {
        target: 'http://backend:8000',
        changeOrigin: true,
        secure: false,
      },
      '/uploads': {
        target: 'http://backend:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },
})
