import { useEffect, useState, type FormEvent } from 'react'
import Editor from '@monaco-editor/react'
import ReactMarkdown from 'react-markdown'
import { api, ApiError, type Files, type Job, type Problem, type ProblemSummary, type Submission } from './api'

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.code === 'workspace_conflict') {
    return 'Workspace changed elsewhere. Reload it before saving again.'
  }
  if (error instanceof ApiError && error.status === 401) {
    return 'Invalid or expired token. Check the token printed by the local API.'
  }
  return error instanceof Error ? error.message : 'Something went wrong.'
}

function countSummary(job: Job): string | null {
  const summary = job.result?.summary
  if (!summary) return null
  return `${summary.passed} passed · ${summary.failed} failed · ${summary.errors} errors · ${summary.skipped} skipped`
}

function resultTone(job: Job | null): 'pass' | 'fail' | 'pending' {
  if (!job) return 'pending'
  const tests = job.result?.tests ?? []
  if (job.status === 'FAILED' || job.result?.verdict === 'FAIL' ||
      (job.result?.summary?.failed ?? 0) > 0 || (job.result?.summary?.errors ?? 0) > 0 ||
      tests.some((test) => test.status === 'FAILED' || test.status === 'ERROR')) return 'fail'
  if (job.status === 'COMPLETED' && job.result?.verdict === 'PASS') return 'pass'
  return 'pending'
}

export default function App() {
  const [tokenInput, setTokenInput] = useState('')
  const [token, setToken] = useState('')
  const [problems, setProblems] = useState<ProblemSummary[]>([])
  const [problem, setProblem] = useState<Problem | null>(null)
  const [files, setFiles] = useState<Files>({})
  const [savedFiles, setSavedFiles] = useState<Files>({})
  const [revision, setRevision] = useState(0)
  const [activeFile, setActiveFile] = useState('')
  const [submissions, setSubmissions] = useState<Submission[]>([])
  const [job, setJob] = useState<Job | null>(null)
  const [pollingJobId, setPollingJobId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const dirty = Object.keys(files).some((name) => files[name] !== savedFiles[name])

  async function loadProblem(currentToken: string, id: string) {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const [detail, workspace, history] = await Promise.all([
        api.problem(currentToken, id),
        api.workspace(currentToken, id),
        api.submissions(currentToken, id),
      ])
      setProblem(detail)
      setFiles({ ...workspace.files })
      setSavedFiles({ ...workspace.files })
      setRevision(workspace.revision)
      setActiveFile(Object.keys(workspace.files)[0] ?? '')
      setSubmissions(history.submissions)
      setJob(null)
      setPollingJobId(null)
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setBusy(false)
    }
  }

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const currentToken = tokenInput.trim()
    if (!currentToken) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const catalog = await api.problems(currentToken)
      setToken(currentToken)
      setProblems(catalog.problems)
      if (catalog.problems.length) {
        await loadProblem(currentToken, catalog.problems[0].id)
      }
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setBusy(false)
    }
  }

  async function save() {
    if (!problem) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const saved = await api.save(token, problem.id, files, revision)
      setSavedFiles({ ...saved.files })
      setRevision(saved.revision)
      setNotice(`Saved revision ${saved.revision}.`)
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setBusy(false)
    }
  }

  async function reloadWorkspace() {
    if (!problem) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const workspace = await api.workspace(token, problem.id)
      setFiles({ ...workspace.files })
      setSavedFiles({ ...workspace.files })
      setRevision(workspace.revision)
      setNotice(`Loaded revision ${workspace.revision}.`)
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setBusy(false)
    }
  }

  async function start(mode: 'run' | 'submit') {
    if (!problem) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const accepted = await api.start(token, problem.id, mode, { ...files })
      setJob({ jobId: accepted.jobId, problemId: problem.id, mode, status: accepted.status, submissionId: accepted.submissionId })
      setPollingJobId(accepted.jobId)
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (!pollingJobId || !problem) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const problemId = problem.id

    async function poll() {
      try {
        const latest = await api.job(token, pollingJobId!)
        if (cancelled) return
        setJob(latest)
        if (latest.status === 'COMPLETED' || latest.status === 'FAILED') {
          setPollingJobId(null)
          if (latest.mode === 'submit') {
            try {
              const history = await api.submissions(token, problemId)
              if (!cancelled) setSubmissions(history.submissions)
            } catch (cause) {
              if (!cancelled) setError(errorMessage(cause))
            }
          }
          return
        }
      } catch (cause) {
        if (cancelled) return
        setError(`Could not refresh job: ${errorMessage(cause)}`)
      }
      timer = setTimeout(poll, 1000)
    }

    timer = setTimeout(poll, 1000)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [pollingJobId, problem, token])

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <h1>SudoSolver</h1>
        </div>
        {token && <button type="button" className="text-button" onClick={() => window.location.reload()}>Disconnect</button>}
      </header>

      {!token ? (
        <main className="connect-panel">
          <h2>Connect to the local API</h2>
          <p>Start <code>make api-local</code>, then paste the bearer token printed in its terminal.</p>
          <form onSubmit={connect} className="connect-form">
            <label htmlFor="token">Local bearer token</label>
            <input id="token" type="password" autoComplete="off" value={tokenInput} onChange={(event) => setTokenInput(event.target.value)} />
            <button type="submit" disabled={busy || !tokenInput.trim()}>{busy ? 'Connecting…' : 'Connect'}</button>
          </form>
          {error && <p role="alert" className="error">{error}</p>}
        </main>
      ) : (
        <main className="workspace">
          <aside className="problem-panel">
            <label htmlFor="problem-select">Problem</label>
            <select id="problem-select" value={problem?.id ?? ''} disabled={busy || !!pollingJobId} onChange={(event) => loadProblem(token, event.target.value)}>
              {problems.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
            </select>
            {problem ? (
              <>
                <p className="metadata">{problem.difficulty} · {problem.estimatedMinutes} min · Python</p>
                <h2>Instructions</h2>
                <div className="instructions"><ReactMarkdown>{problem.instructions}</ReactMarkdown></div>
                <details>
                  <summary>Visible tests</summary>
                  {Object.entries(problem.visibleTests).map(([name, source]) => (
                    <section key={name}>
                      <h3>{name}</h3>
                      <pre>{source}</pre>
                    </section>
                  ))}
                </details>
              </>
            ) : <p>No problems available.</p>}
          </aside>

          <section className="editor-panel" aria-label="Code workspace">
            {problem && activeFile ? (
              <>
                <div className="file-tabs" role="tablist" aria-label="Editable files">
                  {Object.keys(files).map((name) => (
                    <button key={name} type="button" role="tab" aria-selected={activeFile === name} onClick={() => setActiveFile(name)}>{name}</button>
                  ))}
                </div>
                <div className="editor-frame" data-testid="code-editor">
                  <Editor
                    path={activeFile}
                    language="python"
                    theme="vs-dark"
                    value={files[activeFile]}
                    onChange={(value) => setFiles((current) => ({ ...current, [activeFile]: value ?? '' }))}
                    options={{ minimap: { enabled: false }, fontSize: 14, automaticLayout: true, ariaLabel: `${activeFile} code editor` }}
                  />
                </div>
                <div className="toolbar">
                  <span className="save-state" data-testid="save-state">{dirty ? 'Unsaved changes' : `Saved · revision ${revision}`}</span>
                  <button type="button" className="secondary" onClick={reloadWorkspace} disabled={busy}>Reload workspace</button>
                  <button type="button" className="secondary" onClick={save} disabled={busy || !dirty}>Save</button>
                  <button type="button" onClick={() => start('run')} disabled={busy || !!pollingJobId}>Run Tests</button>
                  <button type="button" onClick={() => start('submit')} disabled={busy || !!pollingJobId}>Submit</button>
                </div>
              </>
            ) : <p className="empty-state">Choose a problem to begin.</p>}
            {error && <p role="alert" className="error">{error}</p>}
            {notice && <p role="status" className="notice">{notice}</p>}
            <div className="output-panel">
              <section aria-label="Latest job result" className={`result-section result-section--${resultTone(job)}`}>
                <h2>Latest result</h2>
                {job ? (
                  <div data-testid="job-result">
                    <p><strong>{job.mode === 'run' ? 'Run' : 'Submit'}</strong> · <span className={job.status === 'FAILED' ? 'status-fail' : ''}>{job.status}</span>{job.result?.verdict && <> · <span className={job.result.verdict === 'PASS' ? 'status-pass' : 'status-fail'}>{job.result.verdict}</span></>}</p>
                    {countSummary(job) && <p>{countSummary(job)}</p>}
                    {job.result?.error && <p className="error">{job.result.error.code}</p>}
                    {job.mode === 'run' && job.result?.tests?.map((test, index) => (
                      <div className="test-result" key={`${test.name}-${index}`}>
                        <strong className={test.status === 'PASSED' ? 'status-pass' : test.status === 'FAILED' || test.status === 'ERROR' ? 'status-fail' : ''}>{test.status}</strong> {test.name}
                        {test.failure && <pre>{test.failure}</pre>}
                      </div>
                    ))}
                  </div>
                ) : <p className="muted">Run the visible tests or submit your solution.</p>}
              </section>
              <section aria-label="Submission history">
                <h2>Submissions</h2>
                {submissions.length ? (
                  <ul className="history">
                    {submissions.map((item) => (
                      <li key={item.submissionId}>{new Date(item.createdAt).toLocaleString()} · {item.status}{item.verdict ? ` · ${item.verdict}` : ''}</li>
                    ))}
                  </ul>
                ) : <p className="muted">No submissions yet.</p>}
              </section>
            </div>
          </section>
        </main>
      )}
    </div>
  )
}
