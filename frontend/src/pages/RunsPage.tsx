import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { GitCompare, Play, PlayCircle, ShieldAlert } from 'lucide-react';
import { api } from '../services/api';
import { errorMessage, useAsync } from '../hooks/useAsync';
import type { GeneratedTest, Page, Project, TestRun } from '../types/api';
import { Badge, Button, Card, EmptyState, ErrorNote, Field, Modal, Notice, PageHeader, Pager, Select, Spinner, StatusBadge } from '../components/ui';
import { DemoNotice, WithProject } from '../features/shared';
import { pct, seconds, timeAgo } from '../utils/format';

const ACTIVE = ['queued', 'preparing', 'running'];

interface ExecStatus { provider: string; isolation: string; python: { available: boolean; reason: string }; javascript: { available: boolean; reason: string } }

export default function RunsPage() {
  return <WithProject>{(p) => <RunsView key={p.id} project={p} />}</WithProject>;
}

function RunsView({ project }: { project: Project }) {
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState(1);
  const [newOpen, setNewOpen] = useState(params.get('new') === '1');
  const [cmp, setCmp] = useState<{ base: string; head: string }>({ base: '', head: '' });
  const exec = useAsync(() => api.get<ExecStatus>(`/api/projects/${project.id}/execution/status`), [project.id]);
  const runs = useAsync(() => api.get<Page<TestRun>>(`/api/projects/${project.id}/runs`, { page, page_size: 20 }), [project.id, page],
    { pollMs: 2000, pollWhile: (d) => !!d?.items.some((r) => ACTIVE.includes(r.status)) });
  const nav = useNavigate();
  useEffect(() => { if (params.get('new')) setParams({}, { replace: true }); }, [params, setParams]);

  const items = runs.data?.items ?? [];
  return (
    <>
      <PageHeader title="Test Runs" description="Every status and count on this page comes from the execution engine. Generated tests that have not executed never appear as passed."
        actions={<Button variant="primary" icon={<Play className="size-4" />} onClick={() => setNewOpen(true)} disabled={!project.latest_snapshot_id}>New test run</Button>} />
      <DemoNotice project={project} />
      {exec.data && <ExecBanner s={exec.data} />}
      {runs.error && <ErrorNote error={runs.error} onRetry={runs.reload} />}
      {runs.loading && !runs.data ? <Spinner /> : items.length === 0 ? (
        <EmptyState icon={<PlayCircle className="size-8" />} title="No test runs yet">Approve generated tests or include the project’s existing tests, then start a run.</EmptyState>
      ) : (<>
        <Card padded={false}>
          <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs text-ink-400"><tr>{['Run', 'Status', 'Language', 'Passed', 'Failed', 'Errors', 'Skipped', 'Coverage', 'Duration', 'Provider', 'Started'].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
            <tbody>{items.map((r) => (
              <tr key={r.id} className="cursor-pointer border-t border-ink-800 hover:bg-ink-850" onClick={() => nav(`/runs/${r.id}`)}>
                <td className="px-3 py-2"><Link to={`/runs/${r.id}`} className="text-accent-300 hover:underline">#{r.id}</Link></td>
                <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
                <td className="px-3 py-2 text-ink-300">{r.language}{r.generated_test_ids.length ? <span className="text-ink-400"> · {r.generated_test_ids.length} gen.</span> : null}</td>
                <td className="px-3 py-2 tabular-nums text-emerald-300">{r.total ? r.passed : '—'}</td>
                <td className="px-3 py-2 tabular-nums text-rose-300">{r.total ? r.failed : '—'}</td>
                <td className="px-3 py-2 tabular-nums text-rose-300">{r.total ? r.errors : '—'}</td>
                <td className="px-3 py-2 tabular-nums text-ink-300">{r.total ? r.skipped : '—'}</td>
                <td className="px-3 py-2 tabular-nums text-ink-300">{r.coverage ? pct(r.coverage.line_percent) : 'not measured'}</td>
                <td className="px-3 py-2 tabular-nums text-ink-300">{seconds(r.duration_seconds)}</td>
                <td className="px-3 py-2 text-ink-400">{r.provider}</td>
                <td className="px-3 py-2 text-ink-400">{timeAgo(r.created_at)}</td>
              </tr>
            ))}</tbody>
          </table>
          </div>
          <div className="px-3 pb-3"><Pager page={page} pageSize={20} total={runs.data?.total ?? 0} onPage={setPage} /></div>
        </Card>
        {items.length >= 2 && (
          <Card title="Compare runs" subtitle="Regressions are reported only for tests present in both runs." className="mt-4">
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Base"><Select value={cmp.base} onChange={(v) => setCmp({ ...cmp, base: v })} options={[{ value: '', label: 'Select…' }, ...items.map((r) => ({ value: String(r.id), label: `#${r.id} · ${r.status}` }))]} /></Field>
              <Field label="Compare with"><Select value={cmp.head} onChange={(v) => setCmp({ ...cmp, head: v })} options={[{ value: '', label: 'Select…' }, ...items.map((r) => ({ value: String(r.id), label: `#${r.id} · ${r.status}` }))]} /></Field>
              <Button icon={<GitCompare className="size-4" />} disabled={!cmp.base || !cmp.head || cmp.base === cmp.head} onClick={() => nav(`/runs/compare/${cmp.base}/${cmp.head}`)}>Compare</Button>
            </div>
          </Card>
        )}
      </>)}
      <NewRunModal open={newOpen} onClose={() => setNewOpen(false)} project={project} exec={exec.data}
        onStarted={(r) => { setNewOpen(false); void runs.reload(); nav(`/runs/${r.id}`); }} />
    </>
  );
}

function ExecBanner({ s }: { s: ExecStatus }) {
  if (s.python.available || s.javascript.available) {
    return <Notice className="mb-4">Execution provider <b>{s.provider}</b> ({s.isolation}). Python: {s.python.available ? 'available' : s.python.reason}. JavaScript/TypeScript: {s.javascript.available ? 'available' : s.javascript.reason}.</Notice>;
  }
  return (
    <div className="mb-4 flex items-start gap-2 rounded-md border border-violet-500/30 bg-violet-500/5 px-3 py-2 text-sm text-violet-100">
      <ShieldAlert className="mt-0.5 size-4 shrink-0" />
      <div><b>Real test execution is unavailable.</b> {s.python.reason} Runs you start will be recorded with the status <i>Execution unavailable</i> — no results are fabricated. Static analysis, test generation and review keep working.</div>
    </div>
  );
}

function NewRunModal({ open, onClose, project, exec, onStarted }: { open: boolean; onClose: () => void; project: Project; exec?: ExecStatus; onStarted: (r: TestRun) => void }) {
  const [language, setLanguage] = useState(project.languages[0] ?? 'Python');
  const [includeExisting, setIncludeExisting] = useState(true);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const approved = useAsync(() => api.get<Page<GeneratedTest>>(`/api/projects/${project.id}/generated-tests`, { status: 'approved', page_size: 200 }), [project.id, open], { skip: !open });
  const family = (l: string) => (l === 'Python' ? 'py' : 'js');
  const available = (approved.data?.items ?? []).filter((t) => family(t.language) === family(language));
  useEffect(() => { setChosen(new Set(available.map((t) => t.id))); /* default: all approved of this language */ }, [approved.data, language]); // eslint-disable-line react-hooks/exhaustive-deps
  const langAvail = exec ? (language === 'Python' ? exec.python : exec.javascript) : null;

  async function start() {
    setBusy(true); setErr(null);
    try { onStarted(await api.post<TestRun>(`/api/projects/${project.id}/runs`, { language, include_existing: includeExisting, generated_test_ids: [...chosen] })); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Modal open={open} onClose={onClose} title="New test run">
      <div className="space-y-3">
        {err && <ErrorNote error={err} />}
        <Field label="Language"><Select value={language} onChange={setLanguage} className="w-full" options={(project.languages.length ? project.languages : ['Python', 'JavaScript']).map((l) => ({ value: l, label: l === 'Python' ? 'Python (pytest + coverage.py)' : `${l} (Vitest + v8 coverage)` }))} /></Field>
        {langAvail && !langAvail.available && <Notice tone="violet">{langAvail.reason}</Notice>}
        <label className="flex items-center gap-2 text-sm text-ink-200"><input type="checkbox" checked={includeExisting} onChange={(e) => setIncludeExisting(e.target.checked)} className="accent-cyan-500" />Include the project’s existing tests</label>
        <div>
          <div className="mb-1 text-xs font-medium text-ink-300">Approved generated tests ({chosen.size}/{available.length})</div>
          {approved.loading ? <Spinner /> : available.length === 0 ? <p className="text-sm text-ink-400">No approved {language} tests. Approve proposals on the Test Generation page.</p> : (
            <ul className="max-h-60 space-y-1 overflow-y-auto rounded-md border border-ink-700 p-2">
              {available.map((t) => (
                <li key={t.id}><label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-cyan-500" checked={chosen.has(t.id)} onChange={() => { const s = new Set(chosen); if (s.has(t.id)) s.delete(t.id); else s.add(t.id); setChosen(s); }} />
                  <span className="truncate font-mono text-xs text-ink-200">{t.name}</span>{t.generator.startsWith('ai:') && <Badge tone="violet">AI</Badge>}</label></li>
              ))}
            </ul>
          )}
        </div>
        <p className="text-xs text-ink-400">Tests run in a fresh sandbox per job: no network, no application secrets, CPU/memory/process limits and a hard timeout. Third-party dependencies are not installed.</p>
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={start} loading={busy} disabled={!includeExisting && chosen.size === 0}>Start run</Button></div>
      </div>
    </Modal>
  );
}
