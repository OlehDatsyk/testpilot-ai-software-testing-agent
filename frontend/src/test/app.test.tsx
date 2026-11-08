import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Markdown, StatusBadge } from '../components/ui';
import { api, ApiError, tokenStore } from '../services/api';
import { passRate, pct } from '../utils/format';
import { AppProvider } from '../hooks/AppContext';
import App from '../App';

function mockFetch(routes: Record<string, unknown>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const u = new URL(String(input));
    const key = Object.keys(routes).find((k) => u.pathname === k);
    if (!key) return new Response(JSON.stringify({ error: { status: 404, message: 'not found' } }), { status: 404, headers: { 'content-type': 'application/json' } });
    const body = routes[key];
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  });
}

const CAPS = { version: '1.0.0', environment: 'test', ai: { configured: false, provider: null, model: null }, github: { oauth_configured: false, public_repositories: true },
  execution: { provider: 'disabled', available: false, reason: 'disabled', isolation: 'none' }, demo_mode: true, queue: { queued_jobs: 0, oldest_queued_at: null }, limits: { max_repository_size_mb: 50, execution_timeout: 120 } };
const ME = { user: { id: 1, email: 'a@example.com', name: 'Ada', created_at: '2026-01-01T00:00:00Z' }, workspaces: [{ id: 1, name: "Ada's workspace", role: 'owner' }], github: null };
const EMPTY_OVERVIEW = { projects: 0, demo_projects: 0, repositories_analysed: 0, tests_generated: 0, tests_approved: 0, test_runs: 0, tests_executed: 0, passed: 0, failed: 0, errors: 0, skipped: 0, open_findings: 0, open_findings_by_severity: {}, recent_runs: [], recent_activity: [] };

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe('format helpers', () => {
  it('never reports a pass rate when nothing executed', () => {
    expect(passRate(0, 0)).toBeNull();
    expect(passRate(3, 4)).toBe(75);
    expect(pct(null)).toBe('—');
  });
});

describe('StatusBadge', () => {
  it('renders execution statuses honestly', () => {
    render(<><StatusBadge status="execution_unavailable" /><StatusBadge status="partially_passed" /><StatusBadge status="proposed" /></>);
    expect(screen.getByText('Execution unavailable')).toBeInTheDocument();
    expect(screen.getByText('Partially passed')).toBeInTheDocument();
    expect(screen.getByText('Awaiting review')).toBeInTheDocument();
  });
});

describe('Markdown', () => {
  it('renders bold, code and lists without HTML injection', () => {
    const { container } = render(<Markdown text={'**Bold** and `code`\n\n- one\n- two\n\n<img src=x onerror=alert(1)>'} />);
    expect(screen.getByText('Bold').tagName).toBe('STRONG');
    expect(screen.getByText('code').tagName).toBe('CODE');
    expect(container.querySelectorAll('li')).toHaveLength(2);
    expect(container.querySelector('img')).toBeNull();
  });
  it('keeps snake_case identifiers intact and supports a heading line before bullets', () => {
    const { container } = render(<Markdown text={'Latest failures:\n- test_tp_21_average failed\n- _emphasis_ here'} />);
    expect(container.textContent).toContain('test_tp_21_average');
    expect(container.querySelectorAll('li')).toHaveLength(2);
    expect(container.querySelectorAll('em')).toHaveLength(1);
  });
});

describe('api client', () => {
  it('surfaces structured API errors', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { status: 422, message: 'Generated tests must be approved' } }), { status: 422, headers: { 'content-type': 'application/json' } })));
    await expect(api.post('/api/projects/1/runs', {})).rejects.toMatchObject({ status: 422, message: 'Generated tests must be approved' });
  });
  it('reports an unreachable backend clearly', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('network'); }));
    const err = (await api.get('/health').catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toMatch(/Cannot reach the TestPilot API/);
  });
  it('sends the bearer token', async () => {
    tokenStore.set('tok123');
    const f = vi.fn(async () => new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', f);
    await api.get('/api/auth/me');
    const init = (f.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok123');
  });
});

describe('routing', () => {
  it('redirects unauthenticated users to sign in', async () => {
    vi.stubGlobal('fetch', mockFetch({ '/api/system/capabilities': CAPS }));
    render(<MemoryRouter initialEntries={['/runs']}><AppProvider><App /></AppProvider></MemoryRouter>);
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('shows the empty-state onboarding with a labelled demo option', async () => {
    tokenStore.set('tok');
    vi.stubGlobal('fetch', mockFetch({ '/api/system/capabilities': CAPS, '/api/auth/me': ME, '/api/projects': { items: [], total: 0, page: 1, page_size: 200 },
      '/api/analytics/overview': EMPTY_OVERVIEW, '/api/analytics/trends': { days: 30, daily: [], coverage: [], average_run_duration_seconds: null, findings_by_status: {}, activity_by_project: [] } }));
    render(<MemoryRouter initialEntries={['/']}><AppProvider><App /></AppProvider></MemoryRouter>);
    expect(await screen.findByText('Start by adding a project')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Load demo project/ })).toBeInTheDocument();
    expect(screen.getByText(/deliberate defects/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('unavailable')).toBeInTheDocument());
  });
});
