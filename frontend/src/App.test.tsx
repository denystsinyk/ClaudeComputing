import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('@monaco-editor/react', () => ({
  default: ({ value, onChange }: { value: string; onChange: (value: string) => void }) => (
    <textarea aria-label="Code" value={value} onChange={(event) => onChange(event.target.value)} />
  ),
}))

afterEach(() => vi.unstubAllGlobals())

it('loads a workspace, edits a file, saves it, and runs the current snapshot', async () => {
  const calls: Array<{ path: string; method: string; body?: unknown }> = []
  const fetchMock = vi.fn(async (input: string, options: RequestInit) => {
    const path = input.replace('/api', '')
    const method = options.method ?? 'GET'
    const body = options.body ? JSON.parse(options.body as string) : undefined
    calls.push({ path, method, body })
    const payloads: Record<string, object> = {
      'GET /problems': { problems: [{ id: 'task-store', title: 'Task Store', difficulty: 'easy', estimatedMinutes: 25, language: 'python' }] },
      'GET /problems/task-store': { id: 'task-store', title: 'Task Store', difficulty: 'easy', estimatedMinutes: 25, language: 'python', instructions: '# Implement the store\n\nUse `task.py`.', files: { 'task.py': 'old' }, visibleTests: {} },
      'GET /problems/task-store/workspace': { files: { 'task.py': 'old' }, revision: 0, updatedAt: null },
      'GET /problems/task-store/submissions': { submissions: [] },
      'PUT /problems/task-store/workspace': { files: body?.files, revision: 1, updatedAt: '2026-01-01T00:00:00Z' },
      'POST /problems/task-store/run': { jobId: 'job-1', status: 'QUEUED' },
      'GET /jobs/job-1': { jobId: 'job-1', problemId: 'task-store', mode: 'run', status: 'COMPLETED', result: { verdict: 'PASS', summary: { passed: 1, failed: 0, errors: 0, skipped: 0, duration_ms: 1 }, tests: [{ name: 'test_store', status: 'PASSED' }] } },
    }
    return new Response(JSON.stringify(payloads[`${method} ${path}`]), { status: 200 })
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<App />)
  fireEvent.change(screen.getByLabelText('Local bearer token'), { target: { value: 'secret' } })
  fireEvent.click(screen.getByRole('button', { name: 'Connect' }))

  const editor = await screen.findByRole('textbox', { name: 'Code' })
  expect(screen.getByRole('heading', { name: 'Implement the store' })).toBeInTheDocument()
  expect(screen.getByText('task.py', { selector: 'code' })).toBeInTheDocument()
  expect(screen.queryByText('Python interview practice')).not.toBeInTheDocument()
  expect(editor).toHaveValue('old')
  fireEvent.change(editor, { target: { value: 'new code' } })
  expect(screen.getByTestId('save-state')).toHaveTextContent('Unsaved changes')

  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(screen.getByTestId('save-state')).toHaveTextContent('Saved · revision 1'))
  fireEvent.click(screen.getByRole('button', { name: 'Run Tests' }))
  await waitFor(() => expect(calls).toContainEqual({ path: '/problems/task-store/run', method: 'POST', body: { files: { 'task.py': 'new code' } } }))
  await waitFor(() => expect(screen.getByTestId('job-result')).toHaveTextContent('PASS'), { timeout: 2500 })
  expect(screen.getByRole('region', { name: 'Latest job result' })).toHaveClass('result-section--pass')
  expect(screen.getByText('PASSED')).toHaveClass('status-pass')
  expect(calls).toContainEqual({ path: '/problems/task-store/workspace', method: 'PUT', body: { files: { 'task.py': 'new code' }, revision: 0 } })
})

it('uses a red result background when a visible test fails', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: string, options: RequestInit) => {
    const path = input.replace('/api', '')
    const method = options.method ?? 'GET'
    const payloads: Record<string, object> = {
      'GET /problems': { problems: [{ id: 'task-store', title: 'Task Store', difficulty: 'easy', estimatedMinutes: 25, language: 'python' }] },
      'GET /problems/task-store': { id: 'task-store', title: 'Task Store', difficulty: 'easy', estimatedMinutes: 25, language: 'python', instructions: 'Implement the store.', files: { 'task.py': 'old' }, visibleTests: {} },
      'GET /problems/task-store/workspace': { files: { 'task.py': 'old' }, revision: 0, updatedAt: null },
      'GET /problems/task-store/submissions': { submissions: [] },
      'POST /problems/task-store/run': { jobId: 'job-1', status: 'QUEUED' },
      'GET /jobs/job-1': { jobId: 'job-1', problemId: 'task-store', mode: 'run', status: 'COMPLETED', result: { verdict: 'FAIL', summary: { passed: 1, failed: 1, errors: 0, skipped: 0, duration_ms: 1 }, tests: [{ name: 'test_one', status: 'PASSED' }, { name: 'test_two', status: 'FAILED', failure: 'assertion failed' }] } },
    }
    return new Response(JSON.stringify(payloads[`${method} ${path}`]), { status: 200 })
  }))

  render(<App />)
  fireEvent.change(screen.getByLabelText('Local bearer token'), { target: { value: 'secret' } })
  fireEvent.click(screen.getByRole('button', { name: 'Connect' }))
  await screen.findByRole('textbox', { name: 'Code' })
  fireEvent.click(screen.getByRole('button', { name: 'Run Tests' }))

  await waitFor(() => expect(screen.getByRole('region', { name: 'Latest job result' })).toHaveClass('result-section--fail'), { timeout: 2500 })
  expect(screen.getByText('FAILED')).toHaveClass('status-fail')
  expect(screen.getByText('PASSED')).toHaveClass('status-pass')
})
