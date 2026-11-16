import { useEffect, useRef, useState } from 'react'

const API = import.meta.env.VITE_API_BASE || ''
const terminal = ['COMPLETED', 'FAILED', 'CANCELLED']
const domains = { gratuity: 'Gratuity', maternity_benefit: 'Maternity benefit', workplace_harassment: 'Workplace harassment / POSH', general_compliance: 'General compliance', other: 'Other' }
const routes = { ANSWER_WITH_CITATIONS: 'Source passages verified', REQUEST_MORE_INFORMATION: 'More information needed', LEGAL_COUNSEL_REVIEW: 'Legal review recommended' }
const readLast = key => { try { return localStorage.getItem(key) } catch { return null } }
const saveLast = (key, value) => { try { localStorage.setItem(key, value) } catch { /* The inquiry URL still supports refresh recovery. */ } }
const removeLast = key => { try { localStorage.removeItem(key) } catch { /* URL recovery remains available. */ } }
const isRunId = value => /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i.test(value)
const sourceLink = value => { try { const url = new URL(value); return url.protocol === 'https:' ? url.href : null } catch { return null } }
const today = () => new Date().toLocaleDateString('en-CA')

async function request(path, { token, signal, ...options } = {}) {
  const timeout = AbortSignal.timeout(20000)
  const boundedSignal = signal ? AbortSignal.any([signal, timeout]) : timeout
  const response = await fetch(`${path.startsWith('/__') ? '' : API}${path}`, { ...options, signal: boundedSignal, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers } })
  const body = await response.json().catch(() => ({}))
  if (!response.ok && !(path === '/ready' && body.components)) {
    const detail = body.detail
    const errors = detail?.errors || (Array.isArray(detail) ? detail : null)
    const failure = new Error(errors ? errors.map(e => `${e.loc?.filter(x => x !== 'body').join(' · ') || 'Inquiry'}: ${e.msg}`).join(' • ') : typeof detail === 'string' ? detail : `The service returned ${response.status}. Please try again.`)
    failure.status = response.status
    throw failure
  }
  return body
}

function Dialog({ title, onClose, children }) {
  const dialog = useRef(null)
  const close = useRef(onClose)
  close.current = onClose
  useEffect(() => {
    const element = dialog.current
    element.showModal()
    const handle = () => { if (!element.open) close.current() }
    element.addEventListener('close', handle)
    return () => { element.removeEventListener('close', handle); element.close() }
  }, [])
  return <dialog ref={dialog} aria-labelledby="dialog-title" onClick={e => { if (e.target === dialog.current) onClose() }}>
    <div className="dialog-heading"><h2 id="dialog-title">{title}</h2><button className="icon-button" onClick={onClose} aria-label="Close dialog">×</button></div>
    {children}<button className="button secondary" onClick={onClose}>Close</button>
  </dialog>
}

export default function App() {
  const [tokenDraft, setTokenDraft] = useState('')
  const [token, setToken] = useState('')
  const [storageKey, setStorageKey] = useState(null)
  const [automatic, setAutomatic] = useState(false)
  const [localMode, setLocalMode] = useState(false)
  const [accessChecking, setAccessChecking] = useState(true)
  const [accessError, setAccessError] = useState('')
  const [accessVersion, setAccessVersion] = useState(0)
  const [notice, setNotice] = useState('')
  const [runId, setRunId] = useState(null)
  const [run, setRun] = useState(null)
  const [query, setQuery] = useState('')
  const [date, setDate] = useState(today)
  const [domain, setDomain] = useState('general_compliance')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [size, setSize] = useState('')
  const [category, setCategory] = useState('unspecified')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [pollError, setPollError] = useState('')
  const [pollVersion, setPollVersion] = useState(0)
  const [readiness, setReadiness] = useState(null)
  const [readyError, setReadyError] = useState(false)
  const [readyVersion, setReadyVersion] = useState(0)
  const [citation, setCitation] = useState(null)
  const [trace, setTrace] = useState(false)
  const [rating, setRating] = useState('')
  const [reason, setReason] = useState('')
  const [feedback, setFeedback] = useState(null)
  const [feedbackBusy, setFeedbackBusy] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [waitSeconds, setWaitSeconds] = useState(0)
  const generation = useRef(0)
  const activeId = useRef(runId)
  activeId.current = runId
  const attempt = useRef(null)
  const submitAbort = useRef(null)
  const feedbackAbort = useRef(null)
  const resultHeading = useRef(null)
  const accessReady = Boolean(token || automatic)
  const pending = Boolean(runId && !terminal.includes(run?.status) && !pollError)

  useEffect(() => {
    const controller = new AbortController()
    const open = async () => {
      setAccessChecking(true); setAccessError('')
      try {
        let mode
        try { mode = await request('/__local_workspace', { signal: controller.signal }) }
        catch (e) { if (e.name === 'AbortError') return; mode = { enabled: false } }
        if (controller.signal.aborted || mode.enabled !== true) return
        setLocalMode(true)
        const workspace = await request('/api/v1/workspace', { signal: controller.signal })
        if (controller.signal.aborted) return
        const key = `compliance:last:local:${workspace.client_id}`
        setAutomatic(true); setStorageKey(key)
        const stored = new URLSearchParams(location.search).get('run_id') || readLast(key)
        if (stored && isRunId(stored)) selectRun(stored, key)
        else if (stored) { selectRun(null, key); setNotice('The saved inquiry link is invalid. You can submit a new inquiry.') }
      } catch (e) {
        if (!controller.signal.aborted) setAccessError('The local workspace could not open. Check that the backend is running, then retry.')
      } finally { if (!controller.signal.aborted) setAccessChecking(false) }
    }
    open()
    return () => controller.abort()
  }, [accessVersion])

  useEffect(() => {
    if (!pending) { setWaitSeconds(0); return }
    const since = Date.parse(run?.created_at) || Date.now()
    const tick = () => setWaitSeconds(Math.max(0, Math.floor((Date.now() - since) / 1000)))
    tick()
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [pending, runId, run?.created_at])

  useEffect(() => {
    const controller = new AbortController()
    let timer
    const retry = () => { timer = setTimeout(() => setReadyVersion(v => v + 1), 15000) }
    request('/ready', { signal: controller.signal }).then(data => {
      if (controller.signal.aborted) return
      setReadiness(data); setReadyError(false)
      if (!data.infrastructure_ready) retry()
    }).catch(() => {
      if (controller.signal.aborted) return
      setReadyError(true); setReadiness(null); retry()
    })
    return () => { controller.abort(); clearTimeout(timer) }
  }, [readyVersion])

  useEffect(() => {
    if (!runId || !accessReady) return
    const controller = new AbortController()
    let timer
    const poll = async () => {
      try {
        const data = await request(`/api/v1/runs/${runId}`, { token, signal: controller.signal })
        if (controller.signal.aborted || activeId.current !== runId) return
        setRun(previous => terminal.includes(previous?.status) ? previous : data); setPollError('')
        if (!terminal.includes(data.status)) timer = setTimeout(poll, 1500)
      } catch (e) {
        if (e.name === 'AbortError' || controller.signal.aborted || activeId.current !== runId) return
        if (e.status === 404) {
          selectRun(null, storageKey)
          setNotice('That inquiry is unavailable in this workspace. You can submit a new inquiry.')
        } else setPollError(e.message)
      }
    }
    poll()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [runId, token, accessReady, storageKey, pollVersion])

  useEffect(() => {
    setFeedback(null); setRating(''); setReason(''); setFeedbackBusy(false); setCitation(null); setTrace(false)
    return () => feedbackAbort.current?.abort()
  }, [runId])
  useEffect(() => () => { submitAbort.current?.abort(); feedbackAbort.current?.abort(); generation.current++ }, [])

  function selectRun(id, key = storageKey) {
    activeId.current = id
    setRun(null); setPollError(''); setRunId(id)
    if (key) { if (id) saveLast(key, id); else removeLast(key) }
    const url = new URL(window.location.href)
    if (id) url.searchParams.set('run_id', id)
    else url.searchParams.delete('run_id')
    window.history.replaceState(null, '', url)
  }

  async function connect(e) {
    e.preventDefault()
    const current = ++generation.current
    setConnecting(true); setError('')
    const value = tokenDraft.trim()
    try {
      await request('/api/v1/workspace', { token: value })
      const fingerprint = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
      if (current !== generation.current) return
      const key = `compliance:last:${Array.from(new Uint8Array(fingerprint)).map(v => v.toString(16).padStart(2, '0')).join('')}`
      setToken(value); setTokenDraft(''); setStorageKey(key)
      const stored = new URLSearchParams(location.search).get('run_id') || readLast(key)
      if (stored && isRunId(stored)) selectRun(stored, key)
      else if (stored) { selectRun(null, key); setNotice('The saved inquiry link is invalid. You can submit a new inquiry.') }
    } catch (e) { if (current === generation.current) setError(e.message) }
    finally { if (current === generation.current) setConnecting(false) }
  }

  function disconnect() {
    generation.current++; submitAbort.current?.abort(); feedbackAbort.current?.abort()
    setToken(''); setTokenDraft(''); setAutomatic(false); selectRun(null); setStorageKey(null)
    setError(''); setSubmitting(false); setConnecting(false); setCancelling(false)
    attempt.current = null
  }

  async function submit(e) {
    e.preventDefault()
    const current = ++generation.current
    setError(''); setNotice(''); setSubmitting(true)
    const body = JSON.stringify({ query_text: query, scenario_date: date, domain_hint: domain,
      employment_start_date: start || null, employment_end_date: end || null, establishment_size: size ? Number(size) : null, establishment_category: category })
    if (attempt.current?.body !== body) attempt.current = { body, key: crypto.randomUUID() }
    submitAbort.current?.abort()
    const controller = new AbortController(); submitAbort.current = controller
    try {
      const result = await request('/api/v1/queries', { token, signal: controller.signal, method: 'POST', body, headers: { 'Idempotency-Key': attempt.current.key } })
      if (current !== generation.current) return
      selectRun(result.run_id); resultHeading.current?.focus()
      attempt.current = null
    } catch (e) { if (current === generation.current && e.name !== 'AbortError') setError(e.message) }
    finally { if (current === generation.current) setSubmitting(false) }
  }

  async function cancel() {
    const id = runId, current = generation.current
    setCancelling(true)
    try {
      const data = await request(`/api/v1/runs/${id}/cancel`, { token, method: 'POST' })
      if (current === generation.current && activeId.current === id) { setRun(data); setPollError(''); setPollVersion(v => v + 1) }
    } catch (e) { if (current === generation.current && activeId.current === id) setPollError(e.message) }
    finally { if (current === generation.current) setCancelling(false) }
  }

  async function sendFeedback(e) {
    e.preventDefault()
    const id = runId, current = generation.current
    const controller = new AbortController(); feedbackAbort.current = controller
    setFeedbackBusy(true); setFeedback(null)
    try {
      await request('/api/v1/feedback', { token, signal: controller.signal, method: 'POST', body: JSON.stringify({ run_id: id, satisfactory: rating === 'yes', reason: reason || null }) })
      if (current === generation.current && activeId.current === id) setFeedback({ ok: true, text: 'Thank you. Your feedback has been saved.' })
    } catch (e) { if (!controller.signal.aborted && current === generation.current && activeId.current === id) setFeedback({ ok: false, text: e.message }) }
    finally { if (!controller.signal.aborted && current === generation.current && activeId.current === id) setFeedbackBusy(false) }
  }

  return <div className="workspace">
    <a className="skip-link" href="#inquiry">Skip to inquiry</a>
    <header className="topbar"><a className="brand" href="/" aria-label="Compliance Desk home"><span className="brand-mark" aria-hidden="true">§</span><span>COMPLIANCE DESK<small>Workplace advisory</small></span></a>
      <div className="connection"><span className={`status-dot ${readiness?.infrastructure_ready ? 'online' : ''}`} /><span>{readyError ? 'Service unavailable' : readiness ? readiness.infrastructure_ready ? 'Services connected' : 'Services need attention' : 'Checking services'}</span><button className="text-button" onClick={() => setReadyVersion(v => v + 1)}>Recheck</button></div>
    </header>
    <main>
      <div className="page-heading"><div><p className="eyebrow">WORKPLACE COMPLIANCE ADVISORY DESK</p><h1>Clarity for your next decision.</h1><p className="intro">Describe a workplace question. Review the statutory evidence,<br className="desktop-break" /> understand what’s missing, and decide your next step.</p></div><div className="scope-note"><span>RESEARCH SCOPE</span>Indian labour & employment<br />Gratuity · Maternity · POSH</div></div>
      {accessChecking ? <div className="access-bar" role="status">Opening workspace…</div> : localMode ? <div className="access-bar"><span><span className="status-dot online" />{automatic ? 'Local demo workspace ready' : 'Local workspace unavailable'}</span>{accessError && <><span role="alert">{accessError}</span><button className="text-button" onClick={() => setAccessVersion(v => v + 1)}>Retry workspace</button></>}</div> : token ? <div className="access-bar"><span><span className="status-dot online" /> Private workspace connected</span><button className="text-button" onClick={disconnect}>Disconnect</button></div> : <section className="access-panel" aria-labelledby="access-title"><div><h2 id="access-title">Connect your private workspace</h2><p>Use the access token issued by your operator. It stays in memory for this visit.</p></div><form onSubmit={connect}><label className="sr-only" htmlFor="access-token">Access token</label><input id="access-token" type="password" value={tokenDraft} onChange={e => setTokenDraft(e.target.value)} placeholder="Enter access token" autoComplete="off" required /><button className="button secondary" disabled={connecting}>{connecting ? 'Connecting…' : 'Connect'}</button></form></section>}
      {notice && <div role="status" className="notice warning">{notice}</div>}
      {error && <div role="alert" className="notice error">{error}</div>}
      {readiness && !readiness.corpus_ready && readiness.components?.database?.status !== false && <div className="notice warning">The statutory corpus is empty. Source-backed advice will be available after the operator imports verified provisions.</div>}
      {readiness?.components?.database?.status === false && <div className="notice warning">The database is unavailable. Saved inquiries and source-backed advice cannot be checked until it reconnects.</div>}
      {readiness?.components?.worker?.status === false && <div className="notice warning">The processing service is unavailable. Please retry after the operator restores it.</div>}
      <div className="desk-grid">
        <section className="panel inquiry-panel" id="inquiry" aria-labelledby="inquiry-title"><div className="panel-title"><span className="step">01</span><div><h2 id="inquiry-title">Your inquiry</h2><p>Start with the facts you know.</p></div></div>
          <form onSubmit={submit}>
            <label htmlFor="question">Workplace question <span className="required">Required</span></label><textarea id="question" rows="5" minLength="10" maxLength="2000" value={query} onChange={e => setQuery(e.target.value)} placeholder="Describe the situation, your question, and any relevant contract details…" required aria-describedby="question-help" /><div className="field-help" id="question-help"><span>Avoid names and personal identifiers.</span><span>{query.length}/2000</span></div>
            <div className="field-grid"><div><label htmlFor="scenario">Scenario date <span className="required">Required</span></label><input id="scenario" type="date" value={date} onChange={e => setDate(e.target.value)} required /><p className="hint">The date to assess the law against.</p></div><div><label htmlFor="domain">Topic</label><select id="domain" value={domain} onChange={e => setDomain(e.target.value)}>{Object.entries(domains).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></div></div>
            <fieldset><legend>Employment & establishment <span>Optional</span></legend><p className="hint">These details help assess applicability. Leave unknown facts blank.</p><div className="field-grid"><div><label htmlFor="start">Employment start</label><input id="start" type="date" value={start} max={date} onChange={e => setStart(e.target.value)} /></div><div><label htmlFor="end">Employment end</label><input id="end" type="date" value={end} min={start || undefined} onChange={e => setEnd(e.target.value)} /><p className="hint">A planned end date may be in the future.</p></div><div><label htmlFor="headcount">Employee headcount</label><input id="headcount" type="number" min="1" max="1000000" step="1" value={size} onChange={e => setSize(e.target.value)} placeholder="e.g. 50" /></div><div><label htmlFor="category">Establishment type</label><select id="category" value={category} onChange={e => setCategory(e.target.value)}><option value="unspecified">Not specified</option>{['commercial_establishment','factory','mine','plantation','educational_institution','hospital'].map(c => <option key={c} value={c}>{c.replaceAll('_', ' ')}</option>)}</select></div></div></fieldset>
            <button className="button primary submit" disabled={!accessReady || submitting || pending}>{submitting ? 'Submitting inquiry…' : pending ? 'Inquiry in progress' : 'Review compliance inquiry'}<span aria-hidden="true">↗</span></button><p className="submission-note">{!accessReady ? localMode ? 'Waiting for the local workspace to become available.' : 'Connect your workspace to submit an inquiry.' : 'You can leave unknown fields blank. Results may request more details.'}</p>
          </form>
        </section>
        <section className="panel results-panel" aria-labelledby="results-title"><div className="panel-title"><span className="step">02</span><div><h2 id="results-title" tabIndex="-1" ref={resultHeading}>Evidence & guidance</h2><p>A clear outcome, with its supporting sources.</p></div></div>
          {!runId && <div className="empty-state"><span className="empty-icon" aria-hidden="true">§</span><h3>A considered answer starts here.</h3><p>Your inquiry’s outcome and available statutory passages will appear in this workspace.</p><ol className="expectations"><li><span>1</span>Submit the scenario and known facts</li><li><span>2</span>Review the outcome and source passages</li><li><span>3</span>Add context or seek legal review if needed</li></ol></div>}
          {runId && <><div className="run-bar"><span className={`badge ${run?.status?.toLowerCase() || 'queued'}`}>{pollError ? 'Unavailable' : run?.status || 'Loading'}</span><span className="run-id" title={runId}>Inquiry {runId.slice(0, 8)}</span>{pending && <button className="text-button danger" onClick={cancel} disabled={cancelling}>{cancelling ? 'Cancelling…' : 'Cancel inquiry'}</button>}</div>
            {pollError && <div className="notice error" role="alert">{pollError}<button className="text-button" onClick={() => setPollVersion(v => v + 1)}>Retry status check</button><button className="text-button" onClick={() => selectRun(null)}>Start a new inquiry</button></div>}
            {pending && !pollError && <div className="working" role="status"><span className="spinner" aria-hidden="true" /><h3>{run?.status === 'RUNNING' ? 'Reviewing your inquiry' : waitSeconds >= 15 ? 'Processing has not started yet' : 'Waiting for processing'}</h3><p>{waitSeconds >= 15 && run?.status === 'QUEUED' ? 'The queue is taking longer than expected. You can cancel this inquiry and retry. If it stays queued, ask the operator to check the processing service.' : 'Checking the scenario against available statutory evidence. You can return to this inquiry using its URL.'}</p><p className="hint">Elapsed: {waitSeconds}s</p></div>}
            {run && terminal.includes(run.status) && <div className="outcome" aria-live="polite">{run.prompt_version?.endsWith(':stub') && <div className="notice warning">Test simulation · semantic legal verification was not performed.</div>}<p className="eyebrow">INQUIRY OUTCOME</p><h3>{run.execution_trace?.some(s => s.decision === 'EMPTY_CORPUS') ? 'No verified evidence available' : routes[run.business_route] || (run.status === 'CANCELLED' ? 'Inquiry cancelled' : 'Processing could not finish')}</h3>{run.route_reason && <p>{run.route_reason}</p>}{run.advisory_text && <div className="advisory">{run.advisory_text}</div>}
              {run.citations?.length > 0 && <section className="citations"><h4>Supporting statutory passages <span>{run.citations.length}</span></h4>{run.citations.map((c,i) => <button className="citation" key={`${c.provision_id}-${i}`} onClick={() => setCitation(c)}><span className="citation-number">{String(i+1).padStart(2,'0')}</span><span><strong>{c.act}</strong><small>Section {c.section} {c.clause || ''} · {c.legal_status}</small><span className="quote">{c.quoted_text}</span><span className="source-link">Inspect source passage ↗</span></span></button>)}</section>}
              <button className="text-button" onClick={() => setTrace(true)}>View execution record</button>
              {['COMPLETED','FAILED'].includes(run.status) && <section className="feedback"><h4>Was this outcome helpful?</h4>{feedback?.ok ? <p role="status" className="success-text">{feedback.text}</p> : <form onSubmit={sendFeedback}><fieldset className="rating"><legend className="sr-only">Outcome rating</legend><label><input type="radio" name="rating" value="yes" checked={rating === 'yes'} onChange={e => setRating(e.target.value)} required /> Yes</label><label><input type="radio" name="rating" value="no" checked={rating === 'no'} onChange={e => setRating(e.target.value)} required /> No</label></fieldset><label htmlFor="feedback-reason" className="sr-only">Optional feedback reason</label><input id="feedback-reason" value={reason} onChange={e => setReason(e.target.value)} maxLength="1000" placeholder="What worked, or what was missing? (optional)" /><button className="button secondary" disabled={feedbackBusy || !rating}>{feedbackBusy ? 'Saving…' : 'Send feedback'}</button>{feedback && <p role="alert" className="error-text">{feedback.text}</p>}</form>}</section>}
            </div>}
          </>}
          <div className="advisory-note"><span aria-hidden="true">ⓘ</span><p>Research guidance supports your judgment. A review recommendation does not send a referral to legal counsel.</p></div>
        </section>
      </div><footer><span>Workplace Compliance Advisory Desk</span><span>Evidence first. Human judgment always.</span></footer>
    </main>
    {citation && <Dialog title="Source passage" onClose={() => setCitation(null)}><p className="eyebrow">{citation.legal_status}</p><h3>{citation.act}</h3><p>Section {citation.section} {citation.clause}</p><blockquote>{citation.quoted_text}</blockquote><p className="hint">Provision ID: <code>{citation.provision_id}</code></p><p className="hint">{citation.notification_ref && <>Notification: {citation.notification_ref}<br /></>}{citation.page_number && <>Page: {citation.page_number}<br /></>}{sourceLink(citation.source_url) ? <a href={sourceLink(citation.source_url)} target="_blank" rel="noopener noreferrer">Open recorded source ↗</a> : "An official source link was not supplied with this result."}</p></Dialog>}
    {trace && run && <Dialog title="Execution record" onClose={() => setTrace(false)}><dl><dt>Inquiry ID</dt><dd><code>{run.run_id}</code></dd><dt>Correlation ID</dt><dd><code>{run.correlation_id}</code></dd><dt>Approved payload digest</dt><dd><code>{run.claim_digest || 'No verified payload'}</code></dd></dl>{run.execution_trace?.length ? <ol className="trace">{run.execution_trace.map((s,i) => <li key={i}><strong>{s.step_name?.replaceAll('_',' ')}</strong><pre>{JSON.stringify(s,null,2)}</pre></li>)}</ol> : <p>No execution steps were recorded for this inquiry.</p>}</Dialog>}
  </div>
}
