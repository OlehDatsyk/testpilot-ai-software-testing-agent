import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Gauge } from 'lucide-react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../services/api';
import { useAsync } from '../hooks/useAsync';
import type { Coverage, Project } from '../types/api';
import { Card, EmptyState, inputCls, Notice, PageHeader, Spinner, Stat } from '../components/ui';
import { DemoNotice, WithProject } from '../features/shared';
import { dateTime, pct } from '../utils/format';
import { chartTheme } from './OverviewPage';

export default function CoveragePage() {
  return <WithProject>{(p) => <CoverageView key={p.id} project={p} />}</WithProject>;
}

function bar(v: number | null | undefined) {
  const n = v ?? 0;
  const color = n >= 80 ? 'bg-emerald-400' : n >= 50 ? 'bg-amber-400' : 'bg-rose-400';
  return <div className="h-1.5 w-full rounded bg-ink-800"><div className={`h-1.5 rounded ${color}`} style={{ width: `${n}%` }} /></div>;
}

function CoverageView({ project }: { project: Project }) {
  const hist = useAsync(() => api.get<Coverage[]>(`/api/projects/${project.id}/coverage`), [project.id]);
  const untested = useAsync(() => api.get<{ measured: boolean; files: string[]; run_id?: number }>(`/api/projects/${project.id}/coverage/untested`), [project.id]);
  const [q, setQ] = useState('');
  if (hist.loading && !hist.data) return <Spinner />;
  const latest = hist.data?.[0];
  // Only compare like with like: coverage.py runs with coverage.py runs, Vitest with Vitest.
  const family = (tool: string) => tool.split(' ')[0];
  const sameTool = latest ? (hist.data ?? []).filter((c) => family(c.tool) === family(latest.tool)) : [];
  const prev = sameTool[1];
  return (
    <>
      <PageHeader title="Coverage" description="Coverage values are taken directly from coverage.py (Python) or Vitest’s v8 provider (JavaScript/TypeScript) during sandboxed runs." />
      <DemoNotice project={project} />
      <Notice className="mb-4">Coverage indicates which code was exercised by the tests — not whether the tests were correct or comprehensive.</Notice>
      {!latest ? (
        <EmptyState icon={<Gauge className="size-8" />} title="Coverage not measured yet" action={<Link to="/runs" className="text-sm text-accent-300 hover:underline">Go to Test Runs</Link>}>
          Coverage appears after a test run executes in an available sandbox. No values are estimated.
        </EmptyState>
      ) : (<>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Line coverage" value={pct(latest.line_percent)} hint={`${latest.lines_covered}/${latest.lines_total} lines · run #${latest.run_id}`} />
          <Stat label="Branch coverage" value={pct(latest.branch_percent)} />
          <Stat label="Function coverage" value={latest.function_percent === null ? '—' : pct(latest.function_percent)} hint={latest.function_percent === null ? `not reported by ${latest.tool.split(' ')[0]}` : undefined} />
          <Stat label="Change vs previous" value={prev && prev.line_percent !== null && latest.line_percent !== null ? `${latest.line_percent - prev.line_percent >= 0 ? '+' : ''}${(latest.line_percent - prev.line_percent).toFixed(1)} pts` : '—'} hint={prev ? `vs run #${prev.run_id} (same tool)` : `no earlier ${family(latest.tool)} measurement`} />
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <Card title="Files" subtitle={`${latest.tool} · ${dateTime(latest.created_at)}`} className="lg:col-span-2" padded={false}
            actions={<input aria-label="Filter files" className={inputCls + ' h-8 w-48'} placeholder="Filter" value={q} onChange={(e) => setQ(e.target.value)} />}>
            <table className="w-full text-sm"><thead className="text-left text-xs text-ink-400"><tr><th className="px-4 py-2 font-medium">File</th><th className="w-40 px-4 py-2 font-medium">Lines</th><th className="px-4 py-2 font-medium">Missing lines</th></tr></thead>
              <tbody>{latest.files.filter((f) => f.path.includes(q)).sort((a, b) => (a.line_percent ?? 0) - (b.line_percent ?? 0)).map((f) => (
                <tr key={f.path} className="border-t border-ink-800"><td className="px-4 py-2 font-mono text-xs text-ink-200">{f.path}</td>
                  <td className="px-4 py-2"><div className="flex items-center gap-2"><span className="w-12 text-right text-xs tabular-nums">{pct(f.line_percent, 0)}</span>{bar(f.line_percent)}</div></td>
                  <td className="px-4 py-2 font-mono text-xs text-ink-400">{f.missing_lines?.length ? f.missing_lines.slice(0, 12).join(', ') + (f.missing_lines.length > 12 ? '…' : '') : '—'}</td></tr>
              ))}</tbody></table>
          </Card>
          <div className="space-y-4">
            <Card title="Uncovered source files" subtitle="Supported source files never imported during the latest measured run">
              {untested.data?.files.length ? <ul className="space-y-1">{untested.data.files.map((f) => <li key={f} className="font-mono text-xs text-amber-200">{f}</li>)}</ul> : <p className="text-sm text-ink-400">None.</p>}
            </Card>
            {sameTool.length > 1 && (
              <Card title="History" subtitle={`${family(latest.tool)} runs only`}>
                <div className="h-40"><ResponsiveContainer><LineChart data={[...sameTool].reverse()}>
                  <CartesianGrid stroke={chartTheme.grid} vertical={false} />
                  <XAxis dataKey="run_id" stroke={chartTheme.axis} fontSize={11} tickFormatter={(v) => `#${v}`} />
                  <YAxis stroke={chartTheme.axis} fontSize={11} domain={[0, 100]} />
                  <Tooltip {...chartTheme.tooltip} formatter={(v: number) => `${v.toFixed(1)}%`} labelFormatter={(v) => `Run #${v}`} />
                  <Line dataKey="line_percent" name="Lines" stroke="#22d3ee" strokeWidth={2} />
                  <Line dataKey="branch_percent" name="Branches" stroke="#a78bfa" strokeWidth={2} />
                </LineChart></ResponsiveContainer></div>
              </Card>
            )}
          </div>
        </div>
      </>)}
    </>
  );
}
