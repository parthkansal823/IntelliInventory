/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

const API = process.env.VITE_API_PROXY ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg'],
      manifest: {
        name: 'IntelliInventory',
        short_name: 'Inventory',
        description: 'AI-native inventory management',
        theme_color: '#4f46e5',
        background_color: '#0b0b0f',
        display: 'standalone',
        start_url: '/',
        icons: [{ src: '/favicon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any maskable' }],
      },
      workbox: { navigateFallbackDenylist: [/^\/api/, /^\/mcp/, /^\/docs/] },
    }),
  ],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 5173,
    proxy: { '/api': { target: API, changeOrigin: true }, '/mcp': { target: API, changeOrigin: true } },
  },
  build: { chunkSizeWarningLimit: 1200 },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test/setup.ts'] },
})
