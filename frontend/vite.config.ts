import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backend = process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  build: {
    rolldownOptions: {
      output: {
        // Stable vendor chunks: cache well across deploys and keep the app chunk small.
        codeSplitting: {
          groups: [
            { name: 'react', test: /node_modules[\\/](react|react-dom|react-router|react-router-dom|scheduler)[\\/]/ },
            { name: 'ui', test: /node_modules[\\/](@base-ui|@floating-ui|cmdk|sonner|lucide-react)[\\/]/ },
            { name: 'data', test: /node_modules[\\/](@tanstack|axios|i18next|react-i18next)[\\/]/ },
          ],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: backend, changeOrigin: true },
      '/media': { target: backend, changeOrigin: true },
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true },
    },
  },
})
