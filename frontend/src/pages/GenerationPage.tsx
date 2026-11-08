import { useState } from 'react';
import { Check, ChevronDown, ChevronRight, Download, FlaskConical, Pencil, Sparkles, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { useApp } from '../hooks/AppContext';
import { errorMessage, useAsync } from '../hooks/useAsync';
import type { GeneratedTest, Page, Project } from '../types/api';
import { Badge, Button, Card, CodeBlock, EmptyState, ErrorNote, Field, inputCls, Notice, PageHeader, Pager, Select, Spinner, StatusBadge } from '../components/ui';
import { DemoNotice, JobLine, useJob, WithProject } from '../features/shared';
import { humanize } from '../utils/format';

export default function GenerationPage() {
  return <WithProject>{(p) => <GenerationView key={p.id} project={p} />}</WithProject>;
}

function GenerationView({ project }: { project: Project }) {
  const { caps } = useApp();
  const nav = useNavigate();
  const [status, setStatus] = useState('proposed');
  const [language, setLanguage] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [useAI, setUseAI] = useState(false);
  const [focus, setFocus] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const list = useAsync(() => api.get<Page<GeneratedTest>>(`/api/projects/${project.id}/generated-tests`, { status, language, page, page_size: 20 }), [project.id, status, language, page]);
  const { job, track, active } = useJob(() => void list.reload());
  const aiOk = !!caps?.ai.configured;

  async function generate() {
    setErr(null);
    try { track(await api.post(`/api/projects/${project.id}/generate`, { use_ai: useAI && aiOk, focus: focus || null })); }
    catch (e) { setErr(errorMessage(e)); }
  }
  async function review(ids: number[], s: string) {
    setErr(null);
    try {
      const r = await api.post<{ updated: number; skipped_invalid: number[] }>(`/api/projects/${project.id}/generated-tests/review`, { ids, status: s });
      if (r.skipped_invalid.length) setErr(`${r.skipped_invalid.length} test(s) failed validation and were not approved.`);
      setSelected(new Set()); await list.reload();
    } catch (e) { setErr(errorMessage(e)); }
  }
  function toggle(id: number) { const s = new Set(selected); if (s.has(id)) s.delete(id); else s.add(id); setSelected(s); }
  const items = list.data?.items ?? [];

  return (
    <>
      <PageHeader title="Test Generation" description="Tests are generated from the analysed source and stored as proposals. Nothing executes until you approve it, and approval never writes to your repository."
        actions={<>
          <Button icon={<Download className="size-4" />} onClick={() => api.download(`/api/projects/${project.id}/generated-tests/export`, `testpilot-tests-${project.id}.zip`).catch((e) => setErr(errorMessage(e)))}>Export approved</Button>
          <Button onClick={() => nav('/runs?new=1')}>Run approved tests</Button>
        </>} />
      <DemoNotice project={project} />
      <Card title="Generate proposals" className="mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className={`flex items-center gap-2 text-sm ${aiOk ? 'text-ink-200' : 'text-ink-400'}`}>
            <input type="checkbox" checked={useAI && aiOk} disabled={!aiOk} onChange={(e) => setUseAI(e.target.checked)} className="accent-cyan-500" />
            <Sparkles className="size-4" />Include AI suggestions
          </label>
          {useAI && aiOk && <div className="min-w-[16rem] flex-1"><Field label="Focus (optional)"><input className={inputCls} value={focus} onChange={(e) => setFocus(e.target.value)} placeholder="e.g. boundary values in pricing" maxLength={500} /></Field></div>}
          <Button variant="primary" icon={<FlaskConical className="size-4" />} onClick={generate} loading={active}>Generate tests</Button>
        </div>
        <div className="mt-3 space-y-2">
          {!aiOk && <Notice>No AI provider is configured, so only rule-based tests are generated: assertions from docstring/JSDoc examples, explicit <code className="font-mono">raise</code>/<code className="font-mono">throw</code> guards, and heuristic edge inputs (flagged for review).</Notice>}
          <JobLine job={job} label="Generation" />
          {job?.status === 'succeeded' && <p className="text-xs text-ink-300">Created {String(job.result.created ?? 0)} proposals from {String(job.result.files_considered ?? 0)} files.{Array.isArray(job.result.ai_messages) && job.result.ai_messages.length ? ` AI: ${(job.result.ai_messages as string[])[0]}` : ''}</p>}
          {err && <ErrorNote error={err} />}
        </div>
      </Card>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Select ariaLabel="Review status" value={status} onChange={(v) => { setStatus(v); setPage(1); setSelected(new Set()); }} options={[{ value: 'proposed', label: 'Awaiting review' }, { value: 'approved', label: 'Approved' }, { value: 'rejected', label: 'Rejected' }, { value: '', label: 'All' }]} />
        <Select ariaLabel="Language" value={language} onChange={(v) => { setLanguage(v); setPage(1); }} options={[{ value: '', label: 'All languages' }, { value: 'Python', label: 'Python' }, { value: 'JavaScript', label: 'JavaScript' }, { value: 'TypeScript', label: 'TypeScript' }]} />
        {items.length > 0 && <Button size="sm" variant="ghost" onClick={() => setSelected(selected.size === items.length ? new Set() : new Set(items.map((t) => t.id)))}>{selected.size === items.length ? 'Clear selection' : 'Select page'}</Button>}
        {selected.size > 0 && <>
          <span className="text-xs text-ink-400">{selected.size} selected</span>
          <Button size="sm" variant="primary" icon={<Check className="size-3.5" />} onClick={() => review([...selected], 'approved')}>Approve</Button>
          <Button size="sm" icon={<X className="size-3.5" />} onClick={() => review([...selected], 'rejected')}>Reject</Button>
        </>}
      </div>

      {list.loading && !list.data ? <Spinner /> : items.length === 0 ? (
        <EmptyState icon={<FlaskConical className="size-8" />} title="No tests in this view">Generate proposals above, or change the filter.</EmptyState>
      ) : (
        <div className="space-y-2">
          {items.map((t) => <TestCard key={t.id} t={t} project={project} selected={selected.has(t.id)} onToggle={() => toggle(t.id)} onChanged={() => list.reload()} />)}
          <Pager page={page} pageSize={20} total={list.data?.total ?? 0} onPage={setPage} />
        </div>
      )}
    </>
  );
}

function TestCard({ t, project, selected, onToggle, onChanged }: { t: GeneratedTest; project: Project; selected: boolean; onToggle: () => void; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [code, setCode] = useState(t.code);
  const [err, setErr] = useState<string | null>(null);
  const invalid = t.validation.syntax_ok === false || (t.validation.forbidden_calls?.length ?? 0) > 0;

  async function patch(body: object) {
    setErr(null);
    try { await api.patch(`/api/projects/${project.id}/generated-tests/${t.id}`, body); setEditing(false); onChanged(); }
    catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <div className={`rounded-lg border bg-ink-900 ${selected ? 'border-accent-500/60' : 'border-ink-700'}`}>
      <div className="flex items-start gap-3 px-3 py-2.5">
        <input type="checkbox" aria-label={`Select ${t.name}`} checked={selected} onChange={onToggle} className="mt-1 accent-cyan-500" />
        <button className="flex min-w-0 flex-1 items-start gap-2 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? <ChevronDown className="mt-0.5 size-4 shrink-0 text-ink-400" /> : <ChevronRight className="mt-0.5 size-4 shrink-0 text-ink-400" />}
          <div className="min-w-0">
            <div className="truncate font-mono text-sm text-ink-100">{t.name}</div>
            <div className="truncate text-xs text-ink-400">{t.description}</div>
          </div>
        </button>
        <div className="hidden shrink-0 flex-wrap justify-end gap-1 md:flex">
          <Badge>{humanize(t.category)}</Badge><Badge tone="accent">{t.framework}</Badge>
          <Badge tone={t.generator.startsWith('ai:') ? 'violet' : 'neutral'} title="Generator">{t.generator.startsWith('ai:') ? 'AI suggestion' : 'rule-based'}</Badge>
          {invalid && <Badge tone="bad">invalid</Badge>}<StatusBadge status={t.status} />
        </div>
      </div>
      {open && (
        <div className="space-y-3 border-t border-ink-800 px-4 py-3 text-sm">
          <dl className="grid gap-3 md:grid-cols-2">
            <div><dt className="text-xs text-ink-400">Target</dt><dd className="font-mono text-xs text-ink-200">{t.target}</dd></div>
            <div><dt className="text-xs text-ink-400">Source file</dt><dd className="font-mono text-xs text-ink-200">{t.target_file}</dd></div>
            <div className="md:col-span-2"><dt className="text-xs text-ink-400">Expected behaviour (what the test asserts)</dt><dd className="text-ink-200">{t.expected_behaviour}</dd></div>
            <div className="md:col-span-2"><dt className="text-xs text-ink-400">Why this test was generated</dt><dd className="text-ink-300">{t.rationale}</dd></div>
          </dl>
          {editing ? (
            <textarea aria-label="Test code" value={code} onChange={(e) => setCode(e.target.value)} spellCheck={false} rows={Math.min(24, code.split('\n').length + 2)}
              className="code w-full rounded-md border border-ink-600 bg-ink-950 p-3 text-ink-100 focus:border-accent-500 focus:outline-none" />
          ) : <CodeBlock code={t.code} />}
          <div className="text-xs text-ink-400">
            Validation: {t.validation.syntax_ok === false ? <span className="text-rose-300">syntax error {t.validation.error}</span> : <span className="text-emerald-300">{t.validation.check ?? 'parses'}</span>}
            {t.validation.forbidden_calls?.length ? <span className="text-rose-300"> · forbidden calls: {t.validation.forbidden_calls.join(', ')}</span> : null}
            {t.validation.edited_by_user && ' · edited by reviewer'} · Generation status: not executed until approved and run.
          </div>
          {err && <ErrorNote error={err} />}
          <div className="flex flex-wrap gap-2">
            {editing ? <>
              <Button size="sm" variant="primary" onClick={() => patch({ code })}>Save (requires re-approval)</Button>
              <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setCode(t.code); }}>Cancel</Button>
            </> : <>
              {t.status !== 'approved' && <Button size="sm" variant="primary" icon={<Check className="size-3.5" />} disabled={invalid} onClick={() => patch({ status: 'approved' })}>Approve</Button>}
              {t.status !== 'rejected' && <Button size="sm" icon={<X className="size-3.5" />} onClick={() => patch({ status: 'rejected' })}>Reject</Button>}
              {t.status !== 'proposed' && <Button size="sm" variant="ghost" onClick={() => patch({ status: 'proposed' })}>Move back to review</Button>}
              <Button size="sm" variant="ghost" icon={<Pencil className="size-3.5" />} onClick={() => setEditing(true)}>Edit</Button>
            </>}
          </div>
        </div>
      )}
    </div>
  );
}
