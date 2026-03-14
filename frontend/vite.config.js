import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { getMockResponse } from './src/utils/mockApi.js'

function mockApiPlugin(apiMode) {
  return {
    name: 'pskc-mock-api',
    configureServer(server) {
      if (apiMode !== 'mock') {
        return
      }

      server.middlewares.use('/api', (req, res, next) => {
        const endpoint = req.url || '/'
        const mockResponse = getMockResponse(endpoint, { method: req.method || 'GET' })

        if (mockResponse === null) {
          next()
          return
        }

        res.setHeader('Content-Type', 'application/json')
        res.end(JSON.stringify(mockResponse))
      })
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiMode = env.VITE_API_MODE || 'auto'
  const effectiveApiMode = apiMode === 'mock' ? 'auto' : apiMode
  const proxyTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [react(), mockApiPlugin(effectiveApiMode)],
    server: {
      host: '0.0.0.0',
      port: 3000,
      proxy:
        effectiveApiMode === 'live' || effectiveApiMode === 'auto'
          ? {
              '/api': {
                target: proxyTarget,
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/api/, ''),
              },
            }
          : undefined,
    },
  }
})
