export type Files = Record<string, string>

export interface ProblemSummary {
  id: string
  title: string
  difficulty: string
  estimatedMinutes: number
  language: 'python'
}

export interface Problem extends ProblemSummary {
  instructions: string
  files: Files
  visibleTests: Files
}

export interface Workspace {
  files: Files
  revision: number
  updatedAt: string | null
}

export interface TestResult {
  name: string
  status: string
  duration_ms?: number
  failure?: string
}

export interface JobResult {
  verdict: 'PASS' | 'FAIL' | null
  summary?: {
    passed: number
    failed: number
    errors: number
    skipped: number
    duration_ms: number
  }
  tests?: TestResult[]
  error?: { code: string }
}

export interface Job {
  jobId: string
  problemId: string
  mode: 'run' | 'submit'
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  submissionId?: string
  result?: JobResult
}

export interface Submission {
  submissionId: string
  jobId: string
  createdAt: string
  status: Job['status']
  verdict: 'PASS' | 'FAIL' | null
  summary?: JobResult['summary']
  error?: { code: string }
}

export class ApiError extends Error {
  constructor(public status: number, public code: string) {
    super(code.replaceAll('_', ' '))
  }
}

const base = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

async function request<T>(token: string, path: string, method = 'GET', body?: object): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  const payload = await response.json()
  if (!response.ok) {
    throw new ApiError(response.status, payload?.error?.code ?? 'request_failed')
  }
  return payload as T
}

export const api = {
  problems: (token: string) => request<{ problems: ProblemSummary[] }>(token, '/problems'),
  problem: (token: string, id: string) => request<Problem>(token, `/problems/${encodeURIComponent(id)}`),
  workspace: (token: string, id: string) => request<Workspace>(token, `/problems/${encodeURIComponent(id)}/workspace`),
  save: (token: string, id: string, files: Files, revision: number) =>
    request<Workspace>(token, `/problems/${encodeURIComponent(id)}/workspace`, 'PUT', { files, revision }),
  start: (token: string, id: string, mode: 'run' | 'submit', files: Files) =>
    request<Pick<Job, 'jobId' | 'status' | 'submissionId'>>(token, `/problems/${encodeURIComponent(id)}/${mode}`, 'POST', { files }),
  job: (token: string, id: string) => request<Job>(token, `/jobs/${encodeURIComponent(id)}`),
  submissions: (token: string, id: string) =>
    request<{ submissions: Submission[] }>(token, `/problems/${encodeURIComponent(id)}/submissions`),
}
