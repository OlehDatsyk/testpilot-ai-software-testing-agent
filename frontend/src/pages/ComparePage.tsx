import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { api } from '../services/api';
import { useAsync } from '../hooks/useAsync';
import type { Project } from '../types/api';
import { Card, ErrorNote, Notice, PageHeader, Spinner, StatusBadge } from '../components/ui';
import { WithProject } from '../features/shared';
import { pct, seconds } from '../utils/format';

interface Side { id: number; status: string; total: number; passed: number; failed: number; errors: number; skipped: number; duration_seconds: number | null; line_coverage: number | null; snapshot_id: number }
interface Cmp { base: Side; head: Side; comparable: boolean; common_tests: number; regressions: string[]; fixed: string[]; new_tests: string[]; removed_tests: string[]; coverage_delta: number | null; findings: { new: string[]; resolved: string[]; same_snapshot: boolean } | null; note: string | null }

export default function ComparePage() {
  return <WithProject>{(p) => <CompareView project={p} />}</WithProject>;
}

function CompareView({ project }: { project: Project }) {
  const { base, head } = useParams();
  const c = useAsync(() => api.get<Cmp>(`/api/projects/${project.id}/runs/compare/${base}/${head}`), [project.id, base, head]);
  if (c.error) return <ErrorNote error={c.error} />;
  if (!c.data) return <Spinner />;
  const d = c.data;
  const rows: [string, (s: Side) => string][] = [
    ['Status', (s) => s.status], ['Executed', (s) => String(s.total)], ['Passed', (s) => String(s.passed)], ['Failed', (s) => String(s.failed)],
    ['Errors', (s) => String(s.errors)], ['Skipped', (s) => String(s.skipped)], ['Line coverage', (s) => (s.line_coverage === null ? 'not measured' : pct(s.line_coverage))],
    ['Duration', (s) => seconds(s.duration_seconds)], ['Snapshot', (s) => `#${s.snapshot_id}`],
  ];
  return (
    <>
      <Link to="/runs" className="mb-3 inline-flex items-center gap-1 text-sm text-ink-400 hover:text-ink-200"><ArrowLeft className="size-4" />All runs</Link>
      <PageHeader title={`Run #${d.base.id} → Run #${d.head.id}`} description="Comparison of recorded results. Regressions are only reported for tests present in both runs." />
      {d.note && <Notice tone="warn" className="mb-4">{d.note}</Notice>}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Summary" padded={false}>
          <table className="w-full text-sm"><thead className="text-xs text-ink-400"><tr><th className="px-4 py-2 text-left font-medium">Metric</th><th className="px-4 py-2 text-left font-medium">#{d.base.id}</th><th className="px-4 py-2 text-left font-medium">#{d.head.id}</th></tr></thead>
            <tbody>{rows.map(([k, f]) => <tr key={k} className="border-t border-ink-800"><td className="px-4 py-2 text-ink-400">{k}</td><td className="px-4 py-2">{k === 'Status' ? <StatusBadge status={f(d.base)} /> : f(d.base)}</td><td className="px-4 py-2">{k === 'Status' ? <StatusBadge status={f(d.head)} /> : f(d.head)}</td></tr>)}</tbody></table>
          <p className="px-4 py-2 text-xs text-ink-400">{d.common_tests} tests in common · coverage change {d.coverage_delta === null ? 'not comparable' : `${d.coverage_delta > 0 ? '+' : ''}${d.coverage_delta.toFixed(2)} pts`}</p>
        </Card>
        <Card title="Test changes">
          <List title={`Regressions (passed → failed): ${d.regressions.length}`} items={d.regressions} tone="text-rose-300" />
          <List title={`Fixed (failed → passed): ${d.fixed.length}`} items={d.fixed} tone="text-emerald-300" />
          <List title={`Only in #${d.head.id}: ${d.new_tests.length}`} items={d.new_tests} />
          <List title={`Only in #${d.base.id}: ${d.removed_tests.length}`} items={d.removed_tests} />
        </Card>
      </div>
      <Card title="Static findings between snapshots" className="mt-4">
        {!d.findings ? <p className="text-sm text-ink-400">No analysis exists for one of the snapshots, so findings cannot be compared.</p>
          : d.findings.same_snapshot ? <p className="text-sm text-ink-400">Both runs used the same snapshot; findings are identical.</p>
          : <><List title={`New findings: ${d.findings.new.length}`} items={d.findings.new} tone="text-amber-300" /><List title={`Resolved findings: ${d.findings.resolved.length}`} items={d.findings.resolved} tone="text-emerald-300" /></>}
      </Card>
    </>
  );
}

function List({ title, items, tone }: { title: string; items: string[]; tone?: string }) {
  return (
    <div className="mb-3">
      <div className="text-xs font-medium text-ink-300">{title}</div>
      {items.length > 0 && <ul className="mt-1 max-h-40 space-y-0.5 overflow-y-auto">{items.map((i) => <li key={i} className={`truncate font-mono text-xs ${tone ?? 'text-ink-300'}`}>{i}</li>)}</ul>}
    </div>
  );
}
