import { useState, type FormEvent } from 'react';
import { Bug as BugIcon, Download, Plus, Trash2 } from 'lucide-react';
import { api } from '../services/api';
import { errorMessage, useAsync } from '../hooks/useAsync';
import type { Bug, Page, Project } from '../types/api';
import { Badge, Button, Card, CodeBlock, EmptyState, ErrorNote, Field, inputCls, Modal, PageHeader, Pager, Select, SeverityBadge, Spinner, StatusBadge } from '../components/ui';
import { DemoNotice, WithProject } from '../features/shared';
import { SEVERITIES, timeAgo } from '../utils/format';

export default function BugsPage() {
  return <WithProject>{(p) => <BugsView key={p.id} project={p} />}</WithProject>;
}

const STATUSES = ['open', 'in_progress', 'resolved', 'wont_fix'];

function BugsView({ project }: { project: Project }) {
  const [status, setStatus] = useState('');
  const [severity, setSeverity] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Bug | null>(null);
  const [creating, setCreating] = useState(false);
  const list = useAsync(() => api.get<Page<Bug>>(`/api/projects/${project.id}/bugs`, { status, severity, q, page, page_size: 25 }), [project.id, status, severity, q, page]);
  return (
    <>
      <PageHeader title="Bug Reports" description="Create reports from static findings or failed tests (fields are pre-filled only from recorded evidence), or write them manually."
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>New bug report</Button>} />
      <DemoNotice project={project} />
      <div className="mb-3 flex flex-wrap gap-2">
        <input aria-label="Search bugs" className={inputCls + ' max-w-xs'} placeholder="Search title or file" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <Select ariaLabel="Status" value={status} onChange={(v) => { setStatus(v); setPage(1); }} options={[{ value: '', label: 'All statuses' }, ...STATUSES.map((s) => ({ value: s, label: s.replace('_', ' ') }))]} />
        <Select ariaLabel="Severity" value={severity} onChange={(v) => { setSeverity(v); setPage(1); }} options={[{ value: '', label: 'All severities' }, ...SEVERITIES.map((s) => ({ value: s, label: s }))]} />
      </div>
      {list.error && <ErrorNote error={list.error} />}
      {list.loading && !list.data ? <Spinner /> : !list.data?.items.length ? (
        <EmptyState icon={<BugIcon className="size-8" />} title="No bug reports">Open a static-analysis finding or a failed test result and choose “Create bug report”.</EmptyState>
      ) : (
        <Card padded={false}>
          <ul>{list.data.items.map((b) => (
            <li key={b.id}><button onClick={() => setSelected(b)} className="flex w-full items-center gap-3 border-t border-ink-800 px-4 py-3 text-left first:border-0 hover:bg-ink-850">
              <span className="w-10 text-xs text-ink-400">#{b.id}</span>
              <div className="w-16"><SeverityBadge severity={b.severity} /></div>
              <div className="min-w-0 flex-1"><div className="truncate text-sm text-ink-100">{b.title}</div><div className="truncate font-mono text-xs text-ink-400">{b.file_path ?? 'no location'}{b.line ? `:${b.line}` : ''}</div></div>
              <Badge>{b.source_type.replace('_', ' ')}</Badge><StatusBadge status={b.status} /><span className="hidden w-20 text-right text-xs text-ink-400 sm:block">{timeAgo(b.created_at)}</span>
            </button></li>
          ))}</ul>
          <div className="px-4 pb-3"><Pager page={page} pageSize={25} total={list.data.total} onPage={setPage} /></div>
        </Card>
      )}
      {selected && <BugModal bug={selected} project={project} onClose={() => setSelected(null)} onChanged={(b) => { setSelected(b); void list.reload(); }} onDeleted={() => { setSelected(null); void list.reload(); }} />}
      <CreateBugModal open={creating} project={project} onClose={() => setCreating(false)} onCreated={() => { setCreating(false); void list.reload(); }} />
    </>
  );
}

function BugModal({ bug, project, onClose, onChanged, onDeleted }: { bug: Bug; project: Project; onClose: () => void; onChanged: (b: Bug) => void; onDeleted: () => void }) {
  const [draft, setDraft] = useState(bug);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof Bug, v: string) => setDraft({ ...draft, [k]: v || null });
  async function save() {
    setBusy(true); setErr(null);
    try {
      const { title, severity, category, description, reproduction_steps, expected_behaviour, actual_behaviour, suggested_solution, notes, status } = draft;
      onChanged(await api.patch<Bug>(`/api/projects/${project.id}/bugs/${bug.id}`, { title, severity, category, description: description ?? '', reproduction_steps, expected_behaviour, actual_behaviour, suggested_solution, notes, status }));
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  async function del() {
    if (!confirm('Delete this bug report?')) return;
    try { await api.del(`/api/projects/${project.id}/bugs/${bug.id}`); onDeleted(); } catch (e) { setErr(errorMessage(e)); }
  }
  const ta = (k: keyof Bug, label: string, rows = 3) => (
    <Field label={label}><textarea className={inputCls + ' h-auto py-2'} rows={rows} value={(draft[k] as string) ?? ''} onChange={(e) => set(k, e.target.value)} placeholder="Not available — add only if known" /></Field>
  );
  return (
    <Modal open onClose={onClose} title={`Bug #${bug.id}`} wide>
      <div className="space-y-3">
        {err && <ErrorNote error={err} />}
        <Field label="Title"><input className={inputCls} value={draft.title} onChange={(e) => set('title', e.target.value)} /></Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Severity"><Select className="w-full" value={draft.severity} onChange={(v) => set('severity', v)} options={SEVERITIES.map((s) => ({ value: s, label: s }))} /></Field>
          <Field label="Status"><Select className="w-full" value={draft.status} onChange={(v) => set('status', v)} options={STATUSES.map((s) => ({ value: s, label: s.replace('_', ' ') }))} /></Field>
          <Field label="Location"><div className="h-9 truncate pt-2 font-mono text-xs text-ink-300">{bug.file_path ?? '—'}{bug.line ? `:${bug.line}` : ''}</div></Field>
        </div>
        {ta('description', 'Description', 3)}
        <div className="grid gap-3 md:grid-cols-2">{ta('reproduction_steps', 'Reproduction steps')}{ta('expected_behaviour', 'Expected behaviour')}{ta('actual_behaviour', 'Actual behaviour')}{ta('suggested_solution', 'Suggested solution')}</div>
        {bug.error_output && <div><div className="mb-1 text-xs text-ink-400">Error output (recorded)</div><CodeBlock code={bug.error_output} maxHeight={200} /></div>}
        {bug.ai_explanation && <div><div className="mb-1 flex items-center gap-2 text-xs text-ink-400">AI explanation <Badge tone="violet">suggestion</Badge></div><CodeBlock code={bug.ai_explanation} maxHeight={160} /></div>}
        {ta('notes', 'Notes', 2)}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button variant="primary" onClick={save} loading={busy}>Save changes</Button>
          <Button icon={<Download className="size-4" />} onClick={() => api.download(`/api/projects/${project.id}/bugs/${bug.id}/export`, `bug-${bug.id}.md`, { format: 'markdown' })}>Markdown</Button>
          <Button icon={<Download className="size-4" />} onClick={() => api.download(`/api/projects/${project.id}/bugs/${bug.id}/export`, `bug-${bug.id}.json`, { format: 'json' })}>JSON</Button>
          <Button variant="danger" className="ml-auto" icon={<Trash2 className="size-4" />} onClick={del}>Delete</Button>
        </div>
      </div>
    </Modal>
  );
}

function CreateBugModal({ open, project, onClose, onCreated }: { open: boolean; project: Project; onClose: () => void; onCreated: () => void }) {
  const [title, setTitle] = useState('');
  const [severity, setSeverity] = useState('medium');
  const [desc, setDesc] = useState('');
  const [file, setFile] = useState('');
  const [err, setErr] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault(); setErr(null);
    try { await api.post(`/api/projects/${project.id}/bugs`, { title, severity, description: desc, file_path: file || null }); setTitle(''); setDesc(''); setFile(''); onCreated(); }
    catch (e2) { setErr(errorMessage(e2)); }
  }
  return (
    <Modal open={open} onClose={onClose} title="New bug report">
      <form onSubmit={submit} className="space-y-3">
        {err && <ErrorNote error={err} />}
        <Field label="Title"><input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={300} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Severity"><Select className="w-full" value={severity} onChange={setSeverity} options={SEVERITIES.map((s) => ({ value: s, label: s }))} /></Field>
          <Field label="File path (optional)"><input className={inputCls} value={file} onChange={(e) => setFile(e.target.value)} maxLength={500} /></Field>
        </div>
        <Field label="Description"><textarea className={inputCls + ' h-auto py-2'} rows={4} value={desc} onChange={(e) => setDesc(e.target.value)} /></Field>
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" variant="primary">Create</Button></div>
      </form>
    </Modal>
  );
}
