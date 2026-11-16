import test from 'node:test'
import assert from 'node:assert/strict'
import { isLocalRequest, localAuthorization, localWorkspaceConfig } from '../../frontend/local-workspace.mjs'

const workspace = { enabled: true, token: 'synthetic-secret' }
const local = (headers = {}, peer = '127.0.0.1') => ({ socket: { remoteAddress: peer }, headers: { host: '127.0.0.1:3002', ...headers } })

test('automatic credentials are limited to local same-origin requests', () => {
  assert.equal(localAuthorization(local(), workspace), 'Bearer synthetic-secret')
  assert.equal(localAuthorization(local({ origin: 'http://127.0.0.1:3002', 'sec-fetch-site': 'same-origin' }), workspace), 'Bearer synthetic-secret')
  assert.equal(isLocalRequest(local({}, '::ffff:127.0.0.1')), true)
})
test('remote peers cannot spoof loopback through forwarded headers', () => {
  assert.equal(localAuthorization(local({ 'x-forwarded-for': '127.0.0.1' }, '192.0.2.1'), workspace), null)
})
test('foreign origins, DNS-rebinding hosts, and cross-site requests get no credentials', () => {
  for (const headers of [
    { origin: 'https://attacker.invalid' },
    { host: 'attacker.invalid:3002' },
    { origin: 'http://127.0.0.1:9999' },
    { 'sec-fetch-site': 'cross-site' },
    { 'sec-fetch-site': 'same-site' },
  ]) assert.equal(localAuthorization(local(headers), workspace), null)
})
test('explicit client credentials are preserved', () => {
  assert.equal(localAuthorization(local({ authorization: 'Bearer other-user' }), workspace), null)
})
test('automatic access is opt-in and disabled in production', () => {
  assert.deepEqual(localWorkspaceConfig({}), { enabled: false })
  assert.deepEqual(localWorkspaceConfig({ LOCAL_DEMO_ENABLED: 'true', APP_ENV: 'production' }), { enabled: false })
  assert.equal(localAuthorization(local(), { enabled: false }), null)
})
test('only the configured local client is selected server-side', () => {
  const config = localWorkspaceConfig({ LOCAL_DEMO_ENABLED: 'true', AUTH_CLIENT_TOKENS: JSON.stringify({ 'local-demo': 'synthetic-a', reviewer: 'synthetic-b' }) })
  assert.equal(config.clientId, 'local-demo')
  assert.equal(config.token, 'synthetic-a')
})
test('missing and malformed local credentials fail closed without exposing secrets', () => {
  assert.throws(() => localWorkspaceConfig({ LOCAL_DEMO_ENABLED: 'true', AUTH_CLIENT_TOKENS: '{}' }), /Configure/)
  assert.throws(() => localWorkspaceConfig({ LOCAL_DEMO_ENABLED: 'true', AUTH_CLIENT_TOKENS: 'private-invalid-json' }), error => !error.message.includes('private-invalid-json'))
})
