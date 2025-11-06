import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Proxy /api to the backend service inside docker-compose network
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
      '/events': {
        target: 'http://backend:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },
})
