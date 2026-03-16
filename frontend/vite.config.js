import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiMode = env.VITE_API_MODE || 'auto'
  const proxyTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'

  const isProduction = mode === 'production'

  return {
    plugins: [react()],
    
    // Build configuration for production
    build: {
      outDir: 'dist',
      sourcemap: !isProduction, // Disable sourcemap in production
      minify: isProduction ? 'esbuild' : false,
      rollupOptions: {
        output: {
          // Content hashing for cache busting
          entryFileNames: isProduction ? 'assets/[name]-[hash].js' : 'assets/[name].js',
          chunkFileNames: isProduction ? 'assets/[name]-[hash].js' : 'assets/[name].js',
          assetFileNames: isProduction ? 'assets/[name]-[hash][extname]' : 'assets/[name][extname]',
        },
      },
    },

    // Server configuration
    server: {
      host: '0.0.0.0',
      port: 3000,
      proxy:
        apiMode !== 'mock'
          ? {
              '/api': {
                target: proxyTarget,
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/api/, ''),
              },
            }
          : undefined,
    },

    // Preview configuration for testing production build
    preview: {
      host: '0.0.0.0',
      port: 4173,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },

    // Optimize dependencies
    optimizeDeps: {
      include: ['react', 'react-dom', 'react-router-dom', 'recharts', 'framer-motion'],
    },
  }
})
