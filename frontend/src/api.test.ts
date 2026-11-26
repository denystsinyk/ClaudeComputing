import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('local API client', () => {
  it('sends a complete file snapshot and workspace revision with bearer auth', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      files: { 'task.py': 'pass\n' }, revision: 2, updatedAt: '2026-01-01T00:00:00Z',
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await api.save('local-token', 'task-store', { 'task.py': 'pass\n' }, 1)

    expect(fetchMock).toHaveBeenCalledWith('/api/problems/task-store/workspace', {
      method: 'PUT',
      headers: { Authorization: 'Bearer local-token', 'Content-Type': 'application/json' },
      body: JSON.stringify({ files: { 'task.py': 'pass\n' }, revision: 1 }),
    })
  })

  it('surfaces a stale workspace revision as a typed error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ error: { code: 'workspace_conflict' } }), { status: 409 },
    )))

    await expect(api.save('local-token', 'task-store', { 'task.py': '' }, 0))
      .rejects.toEqual(new ApiError(409, 'workspace_conflict'))
  })
})
