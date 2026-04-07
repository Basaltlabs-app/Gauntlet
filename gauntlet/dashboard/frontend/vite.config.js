import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/ws': {
        target: 'ws://127.0.0.1:7878',
        ws: true,
      },
      '/api': {
        target: 'http://127.0.0.1:7878',
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
