import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Bot, Bug, ChevronDown, ChevronRight, FileText, Square } from 'lucide-react';
import { api } from '../services/api';
import { useApp } from '../hooks/AppContext';
import { errorMessage, useAsync } from '../hooks/useAsync';
import type { Project, TestResult, TestRun } from '../types/api';
import { Badge, Button, Card, CodeBlock, ErrorNote, Modal, PageHeader, ResultIcon, Select, Spinner, Stat, StatusBadge } from '../components/ui';
import { DemoNotice, WithProject } from '../features/shared';
import { dateTime, pct, seconds } from '../utils/format';

const ACTIVE = ['queued', 'preparing', 'running'];

export default function RunDetailPage() {
  return <WithProject>{(p) => <RunDetail key={p.id} project={p} />}</WithProject>;
}

function RunDetail({ project }: { project: Project }) {
  const { id } = useParams();
  const runId = Number(id);
  const run = useAsync(() => api.get<TestRun>(`/api/projects/${project.id}/runs/${runId}`), [project.id, runId], { pollMs: 1500, pollWhile: (r) => !!r && ACTIVE.includes(r.status) });
  const results = useAsync(() => api.get<TestResult[]>(`/api/projects/${project.id}/runs/${runId}/results`), [project.id, runId, run.data?.status]);
  const [filter, setFilter] = useState('');
  const [logOpen, setLogOpen] = useState(false);
  const { caps } = useApp();

  if (run.error) return <><BackLink /><ErrorNote error={run.error} /></>;
  if (!run.data) return <Spinner />;
  const r = run.data;
  const shown = (results.data ?? []).filter((x) => !filter || x.status === filter);
  const active = ACTIVE.includes(r.status);

  async function cancel() {
    if (!r.job_id) return;
    try { await api.post(`/api/jobs/${r.job_id}/cancel`); await run.reload(); } catch (e) { alert(errorMessage(e)); }
  }
  return (
    <>
      <BackLink />
      <PageHeader title={`Test run #${r.id}`} description={<span className="flex flex-wrap items-center gap-2"><StatusBadge status={r.status} /> {r.language} · {r.framework} · provider <code className="font-mono">{r.provider}</code> · snapshot #{r.snapshot_id} · {dateTime(r.created_at)}</span>}
        actions={<>{active && <Button variant="danger" icon={<Square className="size-3.5" />} onClick={cancel}>Cancel</Button>}<Button icon={<FileText className="size-4" />} onClick={() => setLogOpen(true)} disabled={active}>Raw log</Button></>} />
      <DemoNotice project={project} />
      {active && <div className="mb-4 rounded-md border border-accent-500/25 bg-accent-500/5 px-3 py-2 text-sm text-ink-200">Status <b>{r.status}</b> as reported by the worker. Results appear when the sandbox finishes; there is no estimated progress.</div>}
      {r.error_message && <div className="mb-4"><ErrorNote error={r.error_message} /></div>}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        <Stat label="Executed" value={r.total} />
        <Stat label="Passed" value={r.passed} tone={r.passed ? 'good' : undefined} />
        <Stat label="Failed" value={r.failed} tone={r.failed ? 'bad' : undefined} />
        <Stat label="Errors" value={r.errors} tone={r.errors ? 'bad' : undefined} />
        <Stat label="Skipped" value={r.skipped} />
        <Stat label="Duration" value={seconds(r.duration_seconds)} />
      </div>
      <Card className="mt-4" title="Coverage" subtitle="Measured during this run. Coverage shows which code executed, not whether the tests were correct or sufficient."
        actions={r.coverage && <Link to="/coverage" className="text-xs text-accent-300 hover:underline">Coverage details</Link>}>
        {r.coverage ? (
          <div className="flex flex-wrap gap-6 text-sm">
            <div><div className="text-xs text-ink-400">Lines</div><div className="text-lg font-semibold">{pct(r.coverage.line_percent)}</div></div>
            <div><div className="text-xs text-ink-400">Branches</div><div className="text-lg font-semibold">{pct(r.coverage.branch_percent)}</div></div>
            <div><div className="text-xs text-ink-400">Functions</div><div className="text-lg font-semibold">{r.coverage.function_percent === null ? <span className="text-sm text-ink-400">not measured by {r.coverage.tool.split(' ')[0]}</span> : pct(r.coverage.function_percent)}</div></div>
            <div><div className="text-xs text-ink-400">Tool</div><div className="text-sm">{r.coverage.tool}</div></div>
          </div>
        ) : <p className="text-sm text-ink-400">Coverage was not measured for this run.</p>}
      </Card>

      <Card className="mt-4" padded={false} title="Results" subtitle="Raw outcomes from the test runner's JUnit report"
        actions={<Select ariaLabel="Filter results" value={filter} onChange={setFilter} options={[{ value: '', label: 'All' }, { value: 'failed', label: 'Failed' }, { value: 'error', label: 'Errors' }, { value: 'passed', label: 'Passed' }, { value: 'skipped', label: 'Skipped' }]} />}>
        {results.loading && !results.data ? <Spinner /> : shown.length === 0 ? <p className="p-6 text-center text-sm text-ink-400">{r.total ? 'No results match the filter.' : 'No results were recorded for this run.'}</p> :
          <ul>{shown.map((x) => <ResultRow key={x.id} x={x} project={project} aiConfigured={!!caps?.ai.configured} onChanged={results.reload} />)}</ul>}
      </Card>
      <LogModal open={logOpen} onClose={() => setLogOpen(false)} path={`/api/projects/${project.id}/runs/${r.id}/log`} />
    </>
  );
}

function BackLink() {
  return <Link to="/runs" className="mb-3 inline-flex items-center gap-1 text-sm text-ink-400 hover:text-ink-200"><ArrowLeft className="size-4" />All runs</Link>;
}

function ResultRow({ x, project, aiConfigured, onChanged }: { x: TestResult; project: Project; aiConfigured: boolean; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const nav = useNavigate();
  const failing = x.status === 'failed' || x.status === 'error';
  async function ai() {
    setBusy(true); setErr(null);
    try { await api.post(`/api/projects/${project.id}/results/${x.id}/ai-analysis`); onChanged(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  async function bug() {
    try { await api.post(`/api/projects/${project.id}/bugs/from-source`, { source_type: 'test_result', source_id: x.id }); nav('/bugs'); } catch (e) { setErr(errorMessage(e)); }
  }
  const ra = x.rule_analysis;
  return (
    <li className="border-t border-ink-800 first:border-0">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 px-4 py-2 text-left hover:bg-ink-850" aria-expanded={open}>
        {open ? <ChevronDown className="size-4 text-ink-400" /> : <ChevronRight className="size-4 text-ink-400" />}
        <ResultIcon status={x.status} />
        <div className="min-w-0 flex-1"><div className="truncate font-mono text-sm text-ink-100">{x.name}</div>
          {failing && x.message && <div className="truncate text-xs text-rose-300/90">{x.message}</div>}</div>
        {x.generated_test_id && <Badge tone="accent">generated #{x.generated_test_id}</Badge>}
        <span className="w-16 text-right text-xs tabular-nums text-ink-400">{seconds(x.duration_seconds)}</span>
      </button>
      {open && (
        <div className="space-y-3 bg-ink-850/50 px-4 pb-4 pl-11 text-sm">
          <dl className="grid gap-2 text-xs md:grid-cols-3">
            <div><dt className="text-ink-400">Test ID</dt><dd className="break-all font-mono text-ink-200">{x.node_id}</dd></div>
            <div><dt className="text-ink-400">File</dt><dd className="break-all font-mono text-ink-200">{x.file_path ?? '—'}</dd></div>
            <div><dt className="text-ink-400">Status</dt><dd><StatusBadge status={x.status} /></dd></div>
          </dl>
          {x.message && <div><div className="mb-1 text-xs text-ink-400">Error message (raw)</div><CodeBlock code={x.message} maxHeight={120} /></div>}
          {x.traceback && <div><div className="mb-1 text-xs text-ink-400">Stack trace (raw)</div><CodeBlock code={x.traceback} maxHeight={320} /></div>}
          {ra && failing && (
            <div className="rounded-md border border-amber-500/25 bg-amber-500/5 p-3">
              <div className="mb-1 flex items-center gap-2 text-xs font-semibold text-amber-200">Rule-based explanation <Badge tone="warn">suggestion</Badge></div>
              <p className="text-ink-200">{ra.meaning}</p>
              {ra.location && <p className="mt-1 text-xs text-ink-300">Deepest project frame: <code className="font-mono">{ra.location.file}:{ra.location.line}</code></p>}
              <div className="mt-2 grid gap-2 md:grid-cols-2 text-xs">
                <div><div className="text-ink-400">Possible causes</div><ul className="list-disc pl-4 text-ink-200">{ra.possible_causes.map((c) => <li key={c}>{c}</li>)}</ul></div>
                <div><div className="text-ink-400">Suggested fixes</div><ul className="list-disc pl-4 text-ink-200">{ra.suggested_fixes.map((c) => <li key={c}>{c}</li>)}</ul></div>
              </div>
            </div>
          )}
          {x.ai_analysis && (
            <div className="rounded-md border border-violet-500/30 bg-violet-500/5 p-3">
              <div className="mb-1 flex items-center gap-2 text-xs font-semibold text-violet-200"><Bot className="size-3.5" />AI failure analysis <Badge tone="violet">suggestion · {x.ai_analysis.provider} · confidence {x.ai_analysis.confidence}</Badge></div>
              <p className="text-ink-200">{x.ai_analysis.summary}</p>
              <p className="mt-1 text-xs text-ink-300">Location: {x.ai_analysis.location} · {x.ai_analysis.error_meaning}</p>
              <div className="mt-2 grid gap-2 text-xs md:grid-cols-3">
                <div><div className="text-ink-400">Likely causes</div><ul className="list-disc pl-4">{x.ai_analysis.likely_causes.map((c) => <li key={c}>{c}</li>)}</ul></div>
                <div><div className="text-ink-400">Suggested fixes</div><ul className="list-disc pl-4">{x.ai_analysis.suggested_fixes.map((c) => <li key={c}>{c}</li>)}</ul></div>
                <div><div className="text-ink-400">Additional tests</div><ul className="list-disc pl-4">{x.ai_analysis.additional_tests.map((c) => <li key={c}>{c}</li>)}</ul></div>
              </div>
            </div>
          )}
          {err && <ErrorNote error={err} />}
          {failing && <div className="flex flex-wrap gap-2">
            <Button size="sm" icon={<Bot className="size-3.5" />} onClick={ai} loading={busy} disabled={!aiConfigured} title={aiConfigured ? '' : 'No AI provider configured'}>{x.ai_analysis ? 'Re-run AI analysis' : 'AI failure analysis'}</Button>
            <Button size="sm" variant="ghost" icon={<Bug className="size-3.5" />} onClick={bug}>Create bug report</Button>
          </div>}
        </div>
      )}
    </li>
  );
}

function LogModal({ open, onClose, path }: { open: boolean; onClose: () => void; path: string }) {
  const log = useAsync(() => api.get<string>(path), [path, open], { skip: !open });
  return (
    <Modal open={open} onClose={onClose} title="Raw runner output" wide>
      {log.loading ? <Spinner /> : log.error ? <ErrorNote error={log.error} /> : <CodeBlock code={log.data || '(empty)'} maxHeight={560} />}
    </Modal>
  );
}
