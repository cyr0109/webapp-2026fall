import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // 前端一律打同源的 /api，由 Vite 轉給後端。
      // target 寫死 127.0.0.1 而不是 localhost：macOS 的 localhost 會先解析成 IPv6 (::1)，
      // 但 uvicorn 只聽 IPv4，連過去會失敗。
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
