import { useState } from 'react';
import { Bug, ChevronDown, ChevronRight, RefreshCw, ScanSearch } from 'lucide-react';
import { api } from '../services/api';
import { useApp } from '../hooks/AppContext';
import { errorMessage, useAsync } from '../hooks/useAsync';
import type { Analysis, Finding, Page, Project } from '../types/api';
import { Badge, Button, Card, CodeBlock, EmptyState, ErrorNote, inputCls, Notice, PageHeader, Pager, Select, SeverityBadge, Spinner, Stat, StatusBadge, Tabs } from '../components/ui';
import { DemoNotice, JobLine, useJob, WithProject } from '../features/shared';
import { bytes, dateTime, SEVERITIES } from '../utils/format';
import { useNavigate } from 'react-router-dom';

export default function AnalysisPage() {
  return <WithProject>{(p) => <AnalysisView key={p.id} project={p} />}</WithProject>;
}

function AnalysisView({ project }: { project: Project }) {
  const { refreshProjects } = useApp();
  const [tab, setTab] = useState<'overview' | 'findings' | 'gaps'>('overview');
  const busy = project.status === 'importing' || project.status === 'analysing';
  const a = useAsync(() => api.get<Analysis | null>(`/api/projects/${project.id}/analysis`), [project.id, project.status]);
  const { job, track, active } = useJob(() => { void a.reload(); void refreshProjects(); });
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    setErr(null);
    try { track(await api.post(`/api/projects/${project.id}/analyse`)); void refreshProjects(); } catch (e) { setErr(errorMessage(e)); }
  }

  // While an import/analysis runs in the worker, poll the project list
  useAsync(async () => { if (busy) await refreshProjects(); return null; }, [busy], { pollMs: 2000, pollWhile: () => busy });

  return (
    <>
      <PageHeader title="Repository Analysis" description="Structure, languages, frameworks and dependencies detected from the files in the latest snapshot, plus static-analysis findings."
        actions={<Button variant="primary" icon={<RefreshCw className="size-4" />} onClick={run} loading={active || busy} disabled={!project.latest_snapshot_id}>Run analysis</Button>} />
      <DemoNotice project={project} />
      <div className="mb-4 space-y-2">{err && <ErrorNote error={err} />}<JobLine job={job} label="Analysis" />
        {busy && !job && <div className="flex items-center gap-2 text-xs text-ink-300">Project <StatusBadge status={project.status} /> — processed by the background worker.</div>}
        {project.status === 'error' && <ErrorNote error="The last import or analysis failed. See the job history in Settings → Jobs, or re-import the project." />}
      </div>
      {a.loading && !a.data ? <Spinner /> : !a.data ? (
        <EmptyState icon={<ScanSearch className="size-8" />} title="No analysis yet">
          {project.latest_snapshot_id ? 'Run an analysis to inspect this snapshot.' : busy ? 'The code is being imported; analysis starts automatically.' : 'This project has no code snapshot. Upload an archive or connect a repository.'}
        </EmptyState>
      ) : (<>
        <Tabs value={tab} onChange={setTab} tabs={[{ id: 'overview', label: 'Overview' }, { id: 'findings', label: 'Static analysis findings' }, { id: 'gaps', label: `Testing gaps (${a.data.summary.testing_gaps.length})` }]} />
        {tab === 'overview' && <Overview a={a.data} />}
        {tab === 'findings' && <Findings project={project} analysis={a.data} />}
        {tab === 'gaps' && <Gaps a={a.data} />}
      </>)}
    </>
  );
}

function Overview({ a }: { a: Analysis }) {
  const s = a.summary;
  const deps = [...s.dependencies.python, ...s.dependencies.javascript];
  const devDeps = [...s.dependencies.python_dev, ...s.dependencies.javascript_dev];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Supported source files" value={s.totals.supported_source_files} hint={`${s.totals.files} files in snapshot`} />
        <Stat label="Existing test files" value={s.totals.test_files} />
        <Stat label="Files inspected" value={a.files_inspected} hint={`${a.files_skipped} skipped`} />
        <Stat label="Analysis time" value={`${(a.duration_ms / 1000).toFixed(2)} s`} hint={dateTime(a.created_at)} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Languages" subtitle="By file extension">
          <ul className="space-y-2">{s.languages.map((l) => (
            <li key={l.name} className="flex items-center justify-between text-sm"><span className="text-ink-200">{l.name} {l.supported ? <Badge tone="accent" className="ml-1">supported</Badge> : null}</span><span className="tabular-nums text-ink-400">{l.files} files · {bytes(l.bytes)}</span></li>
          ))}</ul>
        </Card>
        <Card title="Frameworks & tooling" subtitle="From dependency files and imports">
          <div className="flex flex-wrap gap-1.5">{s.frameworks.length ? s.frameworks.map((f) => <Badge key={f}>{f}</Badge>) : <span className="text-sm text-ink-400">None detected</span>}</div>
          <div className="mt-4 text-xs text-ink-400">Test frameworks</div>
          <div className="mt-1 flex flex-wrap gap-1.5">{s.test_frameworks.length ? s.test_frameworks.map((f) => <Badge key={f} tone="accent">{f}</Badge>) : <span className="text-sm text-ink-400">None detected</span>}</div>
          <div className="mt-4 text-xs text-ink-400">Test commands</div>
          <div className="mt-1 space-y-1">{s.test_commands.length ? s.test_commands.map((c) => <code key={c} className="block font-mono text-xs text-ink-200">{c}</code>) : <span className="text-sm text-ink-400">None found</span>}</div>
        </Card>
        <Card title="Analysers" subtitle="What actually ran on this snapshot">
          <ul className="space-y-2 text-sm">{Object.entries(a.tools).map(([k, v]) => (
            <li key={k} className="flex items-start justify-between gap-2"><span className="font-mono text-xs text-ink-200">{k}</span>
              <span className="text-right text-xs">{v.status === 'ran' ? <Badge tone="good">ran</Badge> : v.status === 'not_implemented' ? <Badge>not implemented</Badge> : <Badge tone="warn">{v.status}</Badge>}
                {v.version && <div className="mt-0.5 text-ink-400">{v.version}</div>}{v.reason && <div className="mt-0.5 text-ink-400">{v.reason}</div>}</span></li>
          ))}</ul>
        </Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Structure">
          <dl className="space-y-3 text-sm">
            <div><dt className="text-xs text-ink-400">Source directories</dt><dd className="mt-1 flex flex-wrap gap-1">{s.source_directories.map((d) => <code key={d} className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-xs">{d}</code>)}</dd></div>
            <div><dt className="text-xs text-ink-400">Test directories</dt><dd className="mt-1 flex flex-wrap gap-1">{s.test_directories.length ? s.test_directories.map((d) => <code key={d} className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-xs">{d}</code>) : <span className="text-ink-400">none</span>}</dd></div>
            <div><dt className="text-xs text-ink-400">Configuration files</dt><dd className="mt-1 flex flex-wrap gap-1">{s.config_files.map((d) => <code key={d} className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-xs">{d}</code>)}</dd></div>
            {Object.keys(s.build_scripts).length > 0 && <div><dt className="text-xs text-ink-400">Build scripts</dt><dd className="mt-1 space-y-0.5">{Object.entries(s.build_scripts).map(([k, v]) => <div key={k} className="font-mono text-xs"><span className="text-accent-300">{k}</span>: {v}</div>)}</dd></div>}
          </dl>
        </Card>
        <Card title="Dependencies" subtitle={`${deps.length} runtime · ${devDeps.length} development`}>
          <div className="flex max-h-56 flex-wrap gap-1 overflow-y-auto">{deps.map((d) => <code key={d} className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-xs">{d}</code>)}{devDeps.map((d) => <code key={'d' + d} className="rounded border border-ink-700 px-1.5 py-0.5 font-mono text-xs text-ink-400">{d}</code>)}{!deps.length && !devDeps.length && <span className="text-sm text-ink-400">No dependency files found.</span>}</div>
        </Card>
      </div>
      {s.complexity_top.length > 0 && (
        <Card title="Most complex Python functions" subtitle="Cyclomatic complexity estimated from the AST" padded={false}>
          <table className="w-full text-sm"><tbody>{s.complexity_top.slice(0, 8).map((c) => (
            <tr key={c.file + c.name} className="border-t border-ink-800 first:border-0"><td className="px-4 py-2 font-mono text-xs text-ink-200">{c.file}:{c.line}</td><td className="px-4 py-2">{c.name}</td><td className="px-4 py-2 text-right tabular-nums text-ink-300">{c.complexity}</td></tr>
          ))}</tbody></table>
        </Card>
      )}
      {s.skipped.length > 0 && <Notice>{s.skipped.length} file(s) were not parsed (binary, lock files, or above the size limit) — they are not included in any finding. Example: <code className="font-mono">{s.skipped[0].path}</code> ({s.skipped[0].reason}).</Notice>}
    </div>
  );
}

function Findings({ project, analysis }: { project: Project; analysis: Analysis }) {
  const nav = useNavigate();
  const [severity, setSeverity] = useState('');
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [openId, setOpenId] = useState<number | null>(null);
  const f = useAsync(() => api.get<Page<Finding>>(`/api/projects/${project.id}/findings`, { severity, status, q, page, page_size: 25 }), [project.id, analysis.id, severity, status, q, page]);

  async function setFindingStatus(id: number, s: string) {
    try { await api.patch(`/api/projects/${project.id}/findings/${id}`, { status: s }); await f.reload(); } catch (e) { alert(errorMessage(e)); }
  }
  async function toBug(id: number) {
    try { await api.post(`/api/projects/${project.id}/bugs/from-source`, { source_type: 'finding', source_id: id }); nav('/bugs'); } catch (e) { alert(errorMessage(e)); }
  }

  return (
    <Card padded={false} title="Findings" subtitle="Definite = rule matched unambiguously; Potential = needs human review. None of these are confirmed runtime bugs.">
      <div className="flex flex-wrap gap-2 border-b border-ink-700 p-3">
        <input aria-label="Search findings" className={inputCls + ' max-w-xs'} placeholder="Search title or file" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <Select ariaLabel="Severity" value={severity} onChange={(v) => { setSeverity(v); setPage(1); }} options={[{ value: '', label: 'All severities' }, ...SEVERITIES.map((s) => ({ value: s, label: s }))]} />
        <Select ariaLabel="Status" value={status} onChange={(v) => { setStatus(v); setPage(1); }} options={[{ value: '', label: 'All statuses' }, ...['open', 'accepted', 'false_positive', 'resolved'].map((s) => ({ value: s, label: s.replace('_', ' ') }))]} />
      </div>
      {f.error && <div className="p-3"><ErrorNote error={f.error} /></div>}
      {f.loading && !f.data ? <Spinner /> : f.data?.items.length === 0 ? <p className="p-8 text-center text-sm text-ink-400">No findings match the filters.</p> : (
        <ul>
          {f.data?.items.map((x) => (
            <li key={x.id} className="border-t border-ink-800 first:border-0">
              <button className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-ink-850" onClick={() => setOpenId(openId === x.id ? null : x.id)} aria-expanded={openId === x.id}>
                {openId === x.id ? <ChevronDown className="mt-0.5 size-4 text-ink-400" /> : <ChevronRight className="mt-0.5 size-4 text-ink-400" />}
                <div className="w-16 shrink-0"><SeverityBadge severity={x.severity} /></div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-ink-100">{x.title}</div>
                  <div className="truncate font-mono text-xs text-ink-400">{x.file_path}{x.line ? `:${x.line}` : ''}</div>
                </div>
                <div className="hidden shrink-0 gap-1 sm:flex"><Badge>{x.method}</Badge><Badge tone={x.certainty === 'definite' ? 'accent' : 'warn'}>{x.certainty}</Badge><StatusBadge status={x.status} /></div>
              </button>
              {openId === x.id && (
                <div className="space-y-3 bg-ink-850/60 px-4 pb-4 pl-11 text-sm">
                  <p className="text-ink-200">{x.description}</p>
                  {x.evidence && <div><div className="mb-1 text-xs text-ink-400">Evidence — line {x.line} as read from the file</div><CodeBlock code={x.evidence} maxHeight={120} /></div>}
                  {x.suggestion && <p className="text-ink-300"><span className="text-xs text-ink-400">Suggested correction: </span>{x.suggestion}</p>}
                  <div className="text-xs text-ink-400">Rule <code className="font-mono">{x.rule_id}</code> · category {x.category} · finding #{x.id}</div>
                  <div className="flex flex-wrap gap-2">
                    {(['open', 'accepted', 'false_positive', 'resolved'] as const).map((s) => (
                      <Button key={s} size="sm" variant={x.status === s ? 'primary' : 'secondary'} onClick={() => setFindingStatus(x.id, s)}>{s.replace('_', ' ')}</Button>
                    ))}
                    <Button size="sm" variant="ghost" icon={<Bug className="size-3.5" />} onClick={() => toBug(x.id)}>Create bug report</Button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {f.data && <div className="px-4 pb-3"><Pager page={page} pageSize={25} total={f.data.total} onPage={setPage} /></div>}
    </Card>
  );
}

function Gaps({ a }: { a: Analysis }) {
  const gaps = a.summary.testing_gaps;
  return (
    <Card title="Potential testing gaps" subtitle="Heuristic: source modules whose name is not referenced by any existing test file. Use measured coverage for an exact picture." padded={false}>
      {gaps.length === 0 ? <p className="p-8 text-center text-sm text-ink-400">Every supported module is referenced by at least one test file.</p> : (
        <table className="w-full text-sm"><tbody>{gaps.map((g) => (
          <tr key={g.file} className="border-t border-ink-800 first:border-0"><td className="px-4 py-2 font-mono text-xs text-ink-200">{g.file}</td><td className="px-4 py-2"><Badge tone="accent">{g.language}</Badge></td><td className="px-4 py-2 text-ink-400">{g.reason}</td></tr>
        ))}</tbody></table>
      )}
    </Card>
  );
}
