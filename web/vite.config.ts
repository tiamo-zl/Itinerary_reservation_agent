import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backend = 'http://127.0.0.1:8000'
const proxied = [
  '/chat',
  '/tasks',
  '/sessions',
  '/conversations',
  '/traces',
  '/approvals',
  '/admin',
  '/feedback',
  '/badcases',
]

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5211,
    proxy: Object.fromEntries(
      proxied.map((path) => [path, { target: backend, changeOrigin: true }]),
    ),
  },
})
