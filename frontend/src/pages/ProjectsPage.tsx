import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Archive, FolderGit2, Github, Plus, RefreshCw, Search, Sparkles, Trash2 } from 'lucide-react';
import { api } from '../services/api';
import { useApp } from '../hooks/AppContext';
import { errorMessage, useAsync } from '../hooks/useAsync';
import type { Page, Project } from '../types/api';
import { Badge, Button, Card, EmptyState, ErrorNote, Field, inputCls, Modal, Notice, PageHeader, Select, Spinner, StatusBadge, Tabs } from '../components/ui';
import { timeAgo } from '../utils/format';

type Mode = 'github' | 'upload' | 'manual' | 'demo';

export default function ProjectsPage() {
  const { refreshProjects, setProjectId, caps } = useApp();
  const nav = useNavigate();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [language, setLanguage] = useState('');
  const [open, setOpen] = useState(false);
  const list = useAsync(() => api.get<Page<Project>>('/api/projects', { q, status, language, page_size: 100 }), [q, status, language],
    { pollMs: 2000, pollWhile: (d) => !!d?.items.some((p) => p.status === 'importing' || p.status === 'analysing') });

  async function remove(p: Project) {
    if (!confirm(`Delete project "${p.name}" and all of its analyses, runs and reports? This cannot be undone.`)) return;
    try { await api.del(`/api/projects/${p.id}`); await list.reload(); await refreshProjects(); }
    catch (e) { alert(errorMessage(e)); }
  }
  async function reimport(p: Project) {
    try { await api.post(`/api/projects/${p.id}/import`, {}); await list.reload(); } catch (e) { alert(errorMessage(e)); }
  }
  function openProject(p: Project) { setProjectId(p.id); nav('/analysis'); }

  return (
    <>
      <PageHeader title="Projects" description="Each project holds snapshots of a codebase, its analyses, generated tests, runs and reports."
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>New project</Button>} />
      <div className="mb-4 flex flex-wrap gap-2">
        <div className="relative flex-1 min-w-[14rem]">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-ink-400" />
          <input aria-label="Search projects" className={inputCls + ' pl-8'} placeholder="Search by name, description or repository" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <Select ariaLabel="Status filter" value={status} onChange={setStatus} options={[{ value: '', label: 'Any status' }, ...['ready', 'importing', 'analysing', 'error', 'new'].map((s) => ({ value: s, label: s }))]} />
        <Select ariaLabel="Language filter" value={language} onChange={setLanguage} options={[{ value: '', label: 'Any language' }, ...['Python', 'JavaScript', 'TypeScript'].map((s) => ({ value: s, label: s }))]} />
      </div>
      {list.error && <ErrorNote error={list.error} onRetry={list.reload} />}
      {list.loading && !list.data ? <Spinner /> : list.data && list.data.items.length === 0 ? (
        <EmptyState icon={<FolderGit2 className="size-8" />} title={q || status || language ? 'No matching projects' : 'No projects yet'}
          action={<Button variant="primary" onClick={() => setOpen(true)}>New project</Button>}>Projects you create appear here.</EmptyState>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {list.data?.items.map((p) => (
            <Card key={p.id} className="flex flex-col">
              <div className="flex items-start justify-between gap-2">
                <button onClick={() => openProject(p)} className="min-w-0 text-left">
                  <div className="truncate font-medium text-white hover:text-accent-300">{p.name}</div>
                  <div className="truncate text-xs text-ink-400">{p.github_full_name ?? (p.source_type === 'archive' ? 'Uploaded archive' : p.source_type === 'demo' ? 'Bundled demo project' : 'Manual project')}{p.default_branch && ` @ ${p.default_branch}`}</div>
                </button>
                <div className="flex shrink-0 gap-1">{p.is_demo && <Badge tone="violet">DEMO</Badge>}<StatusBadge status={p.status} /></div>
              </div>
              {p.description && <p className="mt-2 line-clamp-2 text-sm text-ink-300">{p.description}</p>}
              <div className="mt-3 flex flex-wrap gap-1">{p.languages.map((l) => <Badge key={l} tone="accent">{l}</Badge>)}{p.frameworks.slice(0, 4).map((f) => <Badge key={f}>{f}</Badge>)}</div>
              <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
                <div><dt className="text-ink-400">Analysed</dt><dd className="text-ink-200">{timeAgo(p.latest_analysis_at)}</dd></div>
                <div><dt className="text-ink-400">Open findings</dt><dd className="text-ink-200">{p.latest_analysis_at ? p.open_findings : '—'}</dd></div>
                <div><dt className="text-ink-400">Latest run</dt><dd className="text-ink-200">{p.latest_run ? `${p.latest_run.passed}/${p.latest_run.total} passed` : '—'}</dd></div>
              </dl>
              <div className="mt-4 flex items-center gap-2 border-t border-ink-800 pt-3">
                <Button size="sm" onClick={() => openProject(p)}>Open</Button>
                {(p.source_type === 'github' || p.source_type === 'demo') && <Button size="sm" variant="ghost" icon={<RefreshCw className="size-3.5" />} onClick={() => reimport(p)} disabled={p.status === 'importing' || p.status === 'analysing'}>Re-import</Button>}
                <Button size="sm" variant="ghost" className="ml-auto text-rose-300" icon={<Trash2 className="size-3.5" />} onClick={() => remove(p)} aria-label={`Delete ${p.name}`}>Delete</Button>
              </div>
            </Card>
          ))}
        </div>
      )}
      <NewProjectModal open={open} onClose={() => setOpen(false)} demoEnabled={caps?.demo_mode !== false} maxMb={caps?.limits.max_repository_size_mb ?? 50}
        onCreated={async (p) => { setOpen(false); await list.reload(); await refreshProjects(); setProjectId(p.id); }} />
    </>
  );
}

interface Lookup { full_name: string; description: string; private: boolean; default_branch: string; branches: { name: string }[] }

function NewProjectModal({ open, onClose, onCreated, demoEnabled, maxMb }: { open: boolean; onClose: () => void; onCreated: (p: Project) => void; demoEnabled: boolean; maxMb: number }) {
  const [mode, setMode] = useState<Mode>('github');
  const [repo, setRepo] = useState('');
  const [lookup, setLookup] = useState<Lookup | null>(null);
  const [branch, setBranch] = useState('');
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function doLookup() {
    setBusy(true); setErr(null); setLookup(null);
    try { const l = await api.get<Lookup>('/api/github/lookup', { repository: repo }); setLookup(l); setBranch(l.default_branch); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      let p: Project;
      if (mode === 'github') p = await api.post<Project>('/api/projects/github', { repository: repo, branch: branch || null, name: name || null });
      else if (mode === 'upload') {
        if (!file) throw new Error('Choose an archive file');
        if (file.size > maxMb * 1024 * 1024) throw new Error(`Archive exceeds ${maxMb} MB`);
        const f = new FormData(); f.append('name', name || file.name.replace(/\.(zip|tar\.gz|tgz)$/i, '')); f.append('description', desc); f.append('archive', file);
        p = await api.upload<Project>('/api/projects/upload', f);
      } else if (mode === 'demo') p = await api.post<Project>('/api/projects/demo');
      else p = await api.post<Project>('/api/projects', { name, description: desc, repository_url: repo || null });
      setRepo(''); setName(''); setDesc(''); setFile(null); setLookup(null);
      onCreated(p);
    } catch (e2) { setErr(errorMessage(e2)); } finally { setBusy(false); }
  }

  const tabs: { id: Mode; label: React.ReactNode }[] = [
    { id: 'github', label: <span className="flex items-center gap-1.5"><Github className="size-4" />GitHub</span> },
    { id: 'upload', label: <span className="flex items-center gap-1.5"><Archive className="size-4" />Upload archive</span> },
    { id: 'manual', label: 'Manual' },
    ...(demoEnabled ? [{ id: 'demo' as Mode, label: <span className="flex items-center gap-1.5"><Sparkles className="size-4" />Demo</span> }] : []),
  ];
  return (
    <Modal open={open} onClose={onClose} title="New project">
      <Tabs tabs={tabs} value={mode} onChange={(m) => { setMode(m); setErr(null); }} />
      <form onSubmit={submit} className="space-y-3">
        {err && <ErrorNote error={err} />}
        {mode === 'github' && (<>
          <Field label="Repository" hint="Public repositories work without connecting GitHub. Private repositories require connecting GitHub in Settings.">
            <div className="flex gap-2"><input className={inputCls} placeholder="owner/name or https://github.com/owner/name" value={repo} onChange={(e) => setRepo(e.target.value)} required />
              <Button type="button" onClick={doLookup} loading={busy && !lookup} disabled={!repo}>Look up</Button></div>
          </Field>
          {lookup && (<>
            <Notice>{lookup.full_name} · {lookup.private ? 'private' : 'public'}{lookup.description && ` · ${lookup.description}`}</Notice>
            <Field label="Branch"><Select value={branch} onChange={setBranch} options={lookup.branches.map((b) => ({ value: b.name, label: b.name }))} className="w-full" /></Field>
          </>)}
          <Field label="Project name (optional)"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></Field>
          <p className="text-xs text-ink-400">TestPilot downloads a read-only snapshot. It never pushes, comments or modifies the repository.</p>
        </>)}
        {mode === 'upload' && (<>
          <Field label="Archive (.zip, .tar.gz)" hint={`Max ${maxMb} MB. Archives are treated as untrusted: path traversal, links and oversize content are rejected; node_modules/.git are skipped.`}>
            <input type="file" accept=".zip,.tar.gz,.tgz" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-sm text-ink-300 file:mr-3 file:rounded file:border-0 file:bg-ink-700 file:px-3 file:py-1.5 file:text-ink-100" required />
          </Field>
          <Field label="Project name"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder="Defaults to the file name" /></Field>
          <Field label="Description"><input className={inputCls} value={desc} onChange={(e) => setDesc(e.target.value)} maxLength={2000} /></Field>
        </>)}
        {mode === 'manual' && (<>
          <Field label="Project name"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} /></Field>
          <Field label="Description"><input className={inputCls} value={desc} onChange={(e) => setDesc(e.target.value)} maxLength={2000} /></Field>
          <Field label="Repository URL (reference only)"><input className={inputCls} value={repo} onChange={(e) => setRepo(e.target.value)} maxLength={500} /></Field>
          <p className="text-xs text-ink-400">A manual project has no code until you upload an archive. Use it for tracking bug reports.</p>
        </>)}
        {mode === 'demo' && (
          <Notice tone="violet">Loads <b>Corner Shop Inventory</b>, a small Python + JavaScript project written specifically for TestPilot. It contains <b>deliberate defects</b> so you can see analysis, generated tests, real execution failures and coverage. It is labelled as demo data everywhere and is not a real customer repository.</Notice>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={busy} disabled={mode === 'github' && !repo}>{mode === 'demo' ? 'Load demo project' : 'Create project'}</Button>
        </div>
      </form>
    </Modal>
  );
}
