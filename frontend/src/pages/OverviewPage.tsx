import { Link } from 'react-router-dom';
import { Activity, FolderGit2, Sparkles } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../services/api';
import { useApp } from '../hooks/AppContext';
import { useAsync } from '../hooks/useAsync';
import type { Overview, Project, Trends } from '../types/api';
import { Badge, Button, Card, EmptyState, ErrorNote, PageHeader, SeverityBadge, Spinner, Stat, StatusBadge } from '../components/ui';
import { humanize, passRate, pct, SEVERITIES, timeAgo } from '../utils/format';
import { useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { errorMessage } from '../hooks/useAsync';

export const chartTheme = {
  grid: '#1d2942', axis: '#64748b',
  tooltip: { contentStyle: { background: '#0b1220', border: '1px solid #2a3856', borderRadius: 6, fontSize: 12 }, labelStyle: { color: '#cbd5e1' } },
};

export default function OverviewPage() {
  const { projects, refreshProjects, setProjectId, caps } = useApp();
  const nav = useNavigate();
  const ov = useAsync(() => api.get<Overview>('/api/analytics/overview'), [projects.length]);
  const tr = useAsync(() => api.get<Trends>('/api/analytics/trends', { days: 30 }), [projects.length]);
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoErr, setDemoErr] = useState<string | null>(null);

  async function loadDemo() {
    setDemoBusy(true);
    try {
      const p = await api.post<Project>('/api/projects/demo');
      await refreshProjects();
      setProjectId(p.id);
      nav('/analysis');
    } catch (e) { setDemoErr(errorMessage(e)); } finally { setDemoBusy(false); }
  }

  if (ov.loading && !ov.data) return <Spinner />;
  if (ov.error) return <ErrorNote error={ov.error} onRetry={ov.reload} />;
  const o = ov.data!;

  if (o.projects === 0) {
    return (
      <>
        <PageHeader title="Overview" description="Your workspace has no projects yet." />
        <EmptyState icon={<FolderGit2 className="size-9" />} title="Start by adding a project"
          action={<div className="flex flex-wrap justify-center gap-2">
            <Link to="/projects"><Button variant="primary">Create a project</Button></Link>
            {caps?.demo_mode !== false && <Button onClick={loadDemo} loading={demoBusy} icon={<Sparkles className="size-4" />}>Load demo project</Button>}
          </div>}>
          Connect a GitHub repository, upload a .zip/.tar.gz archive, or explore the workflow with the demo project.
          The demo is code written specifically for TestPilot with deliberate defects — it is labelled as demo data everywhere.
        </EmptyState>
        {demoErr && <div className="mt-3"><ErrorNote error={demoErr} /></div>}
      </>
    );
  }

  const executed = o.tests_executed;
  const rate = passRate(o.passed, executed);
  const daily = tr.data?.daily ?? [];
  return (
    <>
      <PageHeader title="Overview" description={<>Figures below are computed from stored records in this workspace{o.demo_projects ? <> — <Badge tone="violet">includes {o.demo_projects} demo project{o.demo_projects > 1 ? 's' : ''}</Badge></> : null}.</>} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Projects" value={o.projects} hint={`${o.repositories_analysed} analysed`} />
        <Stat label="Tests generated" value={o.tests_generated} hint={`${o.tests_approved} approved`} />
        <Stat label="Tests executed" value={executed} hint={`${o.test_runs} runs`} />
        <Stat label="Open findings" value={o.open_findings} tone={o.open_findings ? 'warn' : undefined} hint="static analysis, latest per project" />
        <Stat label="Passed" value={o.passed} tone={o.passed ? 'good' : undefined} hint={rate === null ? 'nothing executed yet' : `${pct(rate)} of executed`} />
        <Stat label="Failed" value={o.failed} tone={o.failed ? 'bad' : undefined} />
        <Stat label="Errors" value={o.errors} tone={o.errors ? 'bad' : undefined} />
        <Stat label="Skipped" value={o.skipped} />
      </div>
      <p className="mt-2 text-xs text-ink-400">Pass counts cover executed tests only. Generated-but-unexecuted tests are never counted, and pass rate is not a measure of overall software quality.</p>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card title="Test activity (30 days)" subtitle="Generated vs executed, by day" className="lg:col-span-2">
          {daily.length === 0 ? <p className="py-10 text-center text-sm text-ink-400">No activity in the last 30 days.</p> : (
            <div className="h-60">
              <ResponsiveContainer>
                <BarChart data={daily}>
                  <CartesianGrid stroke={chartTheme.grid} vertical={false} />
                  <XAxis dataKey="date" stroke={chartTheme.axis} fontSize={11} tickFormatter={(d: string) => d.slice(5)} />
                  <YAxis stroke={chartTheme.axis} fontSize={11} allowDecimals={false} />
                  <Tooltip {...chartTheme.tooltip} cursor={{ fill: '#141e33' }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="generated" name="Generated" fill="#3d4d6e" radius={[2, 2, 0, 0]} />
                  <Bar dataKey="passed" name="Passed" stackId="x" fill="#34d399" />
                  <Bar dataKey="failed" name="Failed / errors" stackId="x" fill="#fb7185" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
        <Card title="Open findings by severity">
          {o.open_findings === 0 ? <p className="py-10 text-center text-sm text-ink-400">No open findings.</p> : (
            <ul className="space-y-2">
              {SEVERITIES.map((s) => {
                const n = o.open_findings_by_severity[s] ?? 0;
                return (
                  <li key={s} className="flex items-center gap-3">
                    <div className="w-20"><SeverityBadge severity={s} /></div>
                    <div className="h-2 flex-1 rounded bg-ink-800"><div className="h-2 rounded bg-accent-500/70" style={{ width: `${(100 * n) / Math.max(1, o.open_findings)}%` }} /></div>
                    <span className="w-8 text-right text-sm tabular-nums text-ink-200">{n}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card title="Recent test runs" className="lg:col-span-2" padded={false}>
          {o.recent_runs.length === 0 ? <p className="p-6 text-center text-sm text-ink-400">No test runs yet.</p> : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-ink-400"><tr><th className="px-4 py-2 font-medium">Run</th><th className="px-4 py-2 font-medium">Project</th><th className="px-4 py-2 font-medium">Status</th><th className="px-4 py-2 font-medium">Result</th><th className="px-4 py-2 font-medium">When</th></tr></thead>
              <tbody>
                {o.recent_runs.map((r) => (
                  <tr key={r.id} className="border-t border-ink-800 hover:bg-ink-850">
                    <td className="px-4 py-2"><Link className="text-accent-300 hover:underline" to={`/runs/${r.id}`} onClick={() => setProjectId(r.project_id)}>#{r.id}</Link></td>
                    <td className="px-4 py-2 text-ink-200">{r.project}{r.is_demo && <Badge tone="violet" className="ml-1.5">demo</Badge>}</td>
                    <td className="px-4 py-2"><StatusBadge status={r.status} /></td>
                    <td className="px-4 py-2 tabular-nums text-ink-300">{r.total ? `${r.passed}/${r.total} passed` : '—'}</td>
                    <td className="px-4 py-2 text-ink-400">{timeAgo(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Recent activity" actions={<Activity className="size-4 text-ink-400" />}>
          <ul className="space-y-3">
            {o.recent_activity.map((a) => (
              <li key={a.id} className="text-sm">
                <div className="text-ink-200">{humanize(a.action.replace('.', ' '))}</div>
                <div className="text-xs text-ink-400">{a.project ?? '—'} · {a.detail} · {timeAgo(a.created_at)}</div>
              </li>
            ))}
            {o.recent_activity.length === 0 && <li className="text-sm text-ink-400">No activity yet.</li>}
          </ul>
        </Card>
      </div>

      {tr.data && tr.data.coverage.length > 0 && (
        <Card title="Coverage trend" subtitle="Measured line coverage per run" className="mt-4">
          <div className="h-48">
            <ResponsiveContainer>
              <LineChart data={tr.data.coverage}>
                <CartesianGrid stroke={chartTheme.grid} vertical={false} />
                <XAxis dataKey="run_id" stroke={chartTheme.axis} fontSize={11} tickFormatter={(v) => `#${v}`} />
                <YAxis stroke={chartTheme.axis} fontSize={11} domain={[0, 100]} unit="%" />
                <Tooltip {...chartTheme.tooltip} formatter={(v: number) => `${v.toFixed(1)}%`} labelFormatter={(v) => `Run #${v}`} />
                <Line dataKey="line_percent" name="Line coverage" stroke="#22d3ee" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}
    </>
  );
}
