import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Github, Unplug } from 'lucide-react';
import { api } from '../services/api';
import { useApp } from '../hooks/AppContext';
import { errorMessage, useAsync } from '../hooks/useAsync';
import type { Job } from '../types/api';
import { Badge, Button, Card, ErrorNote, Field, inputCls, Notice, PageHeader, StatusBadge } from '../components/ui';
import { dateTime } from '../utils/format';

export default function SettingsPage() {
  const { me, refreshMe, caps, project } = useApp();
  const [params] = useSearchParams();
  const gh = useAsync(() => api.get<{ oauth_configured: boolean; connected: boolean; login: string | null; scopes: string | null }>('/api/github/status'), []);
  const jobs = useAsync(() => (project ? api.get<Job[]>(`/api/projects/${project.id}/jobs`, { limit: 25 }) : Promise.resolve([] as Job[])), [project?.id]);
  const [wsName, setWsName] = useState(me?.workspaces[0]?.name ?? '');
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const ghFlag = params.get('github');

  async function connect(includePrivate: boolean) {
    setErr(null);
    try { const r = await api.get<{ authorize_url: string }>('/api/github/oauth/start', { include_private: includePrivate }); window.location.href = r.authorize_url; }
    catch (e) { setErr(errorMessage(e)); }
  }
  async function disconnect() {
    try { await api.del('/api/github/connection'); await gh.reload(); await refreshMe(); } catch (e) { setErr(errorMessage(e)); }
  }
  async function renameWs() {
    const ws = me?.workspaces[0];
    if (!ws) return;
    try { await api.patch(`/api/workspaces/${ws.id}`, { name: wsName }); await refreshMe(); setSaved(true); setTimeout(() => setSaved(false), 2000); } catch (e) { setErr(errorMessage(e)); }
  }

  return (
    <>
      <PageHeader title="Settings" description="Account, workspace, integrations and platform status." />
      {ghFlag === 'connected' && <Notice className="mb-4">GitHub connected. The token is encrypted on the server and never sent to the browser.</Notice>}
      {(ghFlag === 'error' || ghFlag === 'invalid_state') && <div className="mb-4"><ErrorNote error="GitHub connection failed or the request expired. Please try again." /></div>}
      {err && <div className="mb-4"><ErrorNote error={err} /></div>}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Profile">
          <dl className="space-y-2 text-sm"><div><dt className="text-xs text-ink-400">Name</dt><dd>{me?.user.name}</dd></div><div><dt className="text-xs text-ink-400">Email</dt><dd>{me?.user.email}</dd></div><div><dt className="text-xs text-ink-400">Member since</dt><dd>{dateTime(me?.user.created_at)}</dd></div></dl>
        </Card>
        <Card title="Workspace">
          <Field label="Workspace name"><div className="flex gap-2"><input className={inputCls} value={wsName} onChange={(e) => setWsName(e.target.value)} maxLength={120} /><Button onClick={renameWs}>{saved ? 'Saved' : 'Save'}</Button></div></Field>
          <p className="mt-2 text-xs text-ink-400">Projects, analyses, runs and reports are visible only to members of this workspace. Every API endpoint enforces this on the server.</p>
        </Card>
        <Card title="GitHub" actions={<Github className="size-4 text-ink-400" />}>
          {gh.data?.connected ? (
            <div className="space-y-3 text-sm">
              <p>Connected as <b>{gh.data.login}</b> <Badge>{gh.data.scopes || 'no scopes'}</Badge></p>
              <Button variant="danger" icon={<Unplug className="size-4" />} onClick={disconnect}>Disconnect</Button>
            </div>
          ) : (
            <div className="space-y-3 text-sm text-ink-300">
              <p>Public repositories can be imported without connecting. Connect GitHub to list your repositories or import private ones.</p>
              {gh.data?.oauth_configured ? (
                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => connect(false)}>Connect (public repos only)</Button>
                  <Button variant="primary" onClick={() => connect(true)}>Connect incl. private repos</Button>
                </div>
              ) : <Notice>GitHub OAuth is not configured on this server (<code className="font-mono">GITHUB_CLIENT_ID</code>, <code className="font-mono">GITHUB_CLIENT_SECRET</code>, <code className="font-mono">GITHUB_REDIRECT_URI</code>).</Notice>}
              <p className="text-xs text-ink-400">Private access requests GitHub’s <code className="font-mono">repo</code> scope, because OAuth Apps have no read-only alternative. TestPilot only performs read (GET) requests and never modifies repositories.</p>
            </div>
          )}
        </Card>
        <Card title="Platform status">
          {caps ? (
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between gap-2"><dt className="text-ink-400">Version</dt><dd>{caps.version} ({caps.environment})</dd></div>
              <div className="flex justify-between gap-2"><dt className="text-ink-400">Execution</dt><dd className="text-right">{caps.execution.available ? <Badge tone="good">{caps.execution.provider}</Badge> : <Badge tone="violet">unavailable</Badge>}<div className="mt-0.5 text-xs text-ink-400">{caps.execution.reason}</div></dd></div>
              <div className="flex justify-between gap-2"><dt className="text-ink-400">AI provider</dt><dd>{caps.ai.configured ? `${caps.ai.provider} · ${caps.ai.model}` : 'not configured'}</dd></div>
              <div className="flex justify-between gap-2"><dt className="text-ink-400">Queued jobs</dt><dd>{caps.queue.queued_jobs}{caps.queue.queued_jobs > 0 && caps.queue.oldest_queued_at ? <span className="text-xs text-ink-400"> · oldest {dateTime(caps.queue.oldest_queued_at)}</span> : null}</dd></div>
              <div className="flex justify-between gap-2"><dt className="text-ink-400">Limits</dt><dd className="text-xs">{caps.limits.max_repository_size_mb} MB archives · {caps.limits.execution_timeout}s execution</dd></div>
            </dl>
          ) : <p className="text-sm text-ink-400">Unavailable.</p>}
          {caps && caps.queue.queued_jobs > 0 && <p className="mt-3 text-xs text-amber-200">If jobs stay queued, the background worker is not running (<code className="font-mono">python -m app.worker</code>).</p>}
        </Card>
      </div>
      {project && (
        <Card title={`Background jobs — ${project.name}`} className="mt-4" padded={false}>
          <table className="w-full text-sm"><thead className="text-left text-xs text-ink-400"><tr><th className="px-4 py-2 font-medium">Job</th><th className="px-4 py-2 font-medium">Type</th><th className="px-4 py-2 font-medium">Status</th><th className="px-4 py-2 font-medium">Attempts</th><th className="px-4 py-2 font-medium">Created</th><th className="px-4 py-2 font-medium">Error</th></tr></thead>
            <tbody>{(jobs.data ?? []).map((j) => (
              <tr key={j.id} className="border-t border-ink-800"><td className="px-4 py-2">#{j.id}</td><td className="px-4 py-2">{j.job_type}</td><td className="px-4 py-2"><StatusBadge status={j.status} /></td><td className="px-4 py-2 tabular-nums">{j.attempts}/{j.max_attempts}</td><td className="px-4 py-2 text-ink-400">{dateTime(j.created_at)}</td><td className="max-w-xs truncate px-4 py-2 text-xs text-rose-300" title={j.error ?? ''}>{j.error}</td></tr>
            ))}</tbody></table>
        </Card>
      )}
    </>
  );
}
