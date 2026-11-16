// Server-side development proxy policy. Never import this module into src/.
const loopback = new Set(['localhost', '127.0.0.1', '::1', '[::1]'])
const loopbackPeers = new Set(['127.0.0.1', '::1', '::ffff:127.0.0.1'])

export function isLocalRequest(request) {
  if (!loopbackPeers.has(request.socket?.remoteAddress)) return false
  try {
    const site = request.headers['sec-fetch-site']
    if (site && !['same-origin', 'none'].includes(site)) return false
    const host = request.headers.host
    const local = new URL(`http://${host}`)
    if (!loopback.has(local.hostname)) return false
    const origin = request.headers.origin
    if (origin) {
      const source = new URL(origin)
      if (!['http:', 'https:'].includes(source.protocol) || source.host !== host) return false
    }
    return true
  } catch { return false }
}

export function localWorkspaceConfig(env) {
  const enabled = env.LOCAL_DEMO_ENABLED === 'true' && env.APP_ENV !== 'production'
  if (!enabled) return { enabled: false }
  let tokens
  try { tokens = JSON.parse(env.AUTH_CLIENT_TOKENS || '{}') }
  catch { throw new Error('Local workspace token configuration is invalid.') }
  const clientId = env.LOCAL_DEMO_CLIENT_ID || 'local-demo'
  const token = tokens[clientId]
  if (typeof token !== 'string' || !token.trim()) {
    throw new Error('Configure the local workspace client before enabling automatic access.')
  }
  return { enabled: true, clientId, token }
}

export function localAuthorization(request, workspace) {
  if (!workspace.enabled || request.headers.authorization || !isLocalRequest(request)) return null
  return `Bearer ${workspace.token}`
}
