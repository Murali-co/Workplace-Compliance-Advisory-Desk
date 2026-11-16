import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { isLocalRequest, localAuthorization, localWorkspaceConfig } from './local-workspace.mjs'

export default defineConfig(({ mode }) => {
  const root = fileURLToPath(new URL('..', import.meta.url))
  // These values stay in the Vite server; no token is defined in the client bundle.
  const env = loadEnv(mode, root, '')
  const workspace = localWorkspaceConfig(env)
  const apiTarget = env.COMPLIANCE_API_URL || 'http://127.0.0.1:8010'
  return {
    envDir: root,
    plugins: [react(), {
      name: 'local-demo-workspace',
      apply: 'serve',
      configureServer(server) {
        server.middlewares.use(async (req, res, next) => {
          const path = req.url?.split('?')[0]
          if (path?.startsWith('/api/')) {
            const authorization = localAuthorization(req, workspace)
            if (authorization) {
              try {
                const response = await fetch(`${apiTarget}/`, { signal: AbortSignal.timeout(3000) })
                const identity = await response.json()
                if (identity.service !== 'Workplace Compliance Advisory Desk') throw new Error('Different API')
                req.headers.authorization = authorization
              } catch {
                res.statusCode = 503
                res.setHeader('Content-Type', 'application/json')
                res.end(JSON.stringify({ detail: 'The compliance backend is unavailable on its configured port.' }))
                return
              }
            }
            return next()
          }
          if (path !== '/__local_workspace') return next()
          res.setHeader('Content-Type', 'application/json')
          res.setHeader('Cache-Control', 'no-store')
          if (req.method !== 'GET') { res.statusCode = 405; res.end('{}'); return }
          if (workspace.enabled && !isLocalRequest(req)) {
            res.statusCode = 403
            res.end(JSON.stringify({ detail: 'Automatic demo access is available only on this computer.' }))
            return
          }
          res.end(JSON.stringify({ enabled: workspace.enabled }))
        })
      },
    }],
    server: {
      host: '127.0.0.1',
      port: 4010,
      strictPort: true,
      proxy: {
        '/api': { target: apiTarget },
        '/ready': apiTarget,
        '/health': apiTarget,
      },
    },
  }
})
