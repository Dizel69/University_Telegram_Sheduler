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
    },
  },
})
