import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Build straight into the Flask static folder so one `npm run build`
// is the whole deploy step. Dev server proxies /api to Flask on :5000.
export default defineConfig({
  plugins: [react()],
  build: { outDir: '../static/dist', emptyOutDir: true },
  server: { proxy: { '/api': 'http://127.0.0.1:5000' } },
})
