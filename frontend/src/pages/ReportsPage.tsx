import { useState } from 'react';
import { Download, ExternalLink, FileText } from 'lucide-react';
import { api } from '../services/api';
import { errorMessage, useAsync } from '../hooks/useAsync';
import type { Page, Project, Report, TestRun } from '../types/api';
import { Button, Card, EmptyState, ErrorNote, Field, inputCls, PageHeader, Select, Spinner, StatusBadge } from '../components/ui';
import { DemoNotice, JobLine, useJob, WithProject } from '../features/shared';
import { dateTime } from '../utils/format';

export default function ReportsPage() {
  return <WithProject>{(p) => <ReportsView key={p.id} project={p} />}</WithProject>;
}

function ReportsView({ project }: { project: Project }) {
  const reports = useAsync(() => api.get<Report[]>(`/api/projects/${project.id}/reports`), [project.id]);
  const runs = useAsync(() => api.get<Page<TestRun>>(`/api/projects/${project.id}/runs`, { page_size: 50 }), [project.id]);
  const [title, setTitle] = useState('');
  const [runId, setRunId] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const { job, track, active } = useJob(() => void reports.reload());

  async function create() {
    setErr(null);
    try { track(await api.post(`/api/projects/${project.id}/reports`, { title: title || null, run_id: runId ? Number(runId) : null })); setTitle(''); }
    catch (e) { setErr(errorMessage(e)); }
  }
  const dl = (r: Report, format: 'pdf' | 'html') => api.download(`/api/projects/${project.id}/reports/${r.id}/download`, `testpilot-report-${r.id}.${format}`, { format }).catch((e) => setErr(errorMessage(e)));
  const view = (r: Report) => api.open(`/api/projects/${project.id}/reports/${r.id}/download`, { format: 'html' }).catch((e) => setErr(errorMessage(e)));

  return (
    <>
      <PageHeader title="Reports" description="QA reports in PDF and HTML. Each section is labelled MEASURED (analysis output, executed results, measured coverage), SUGGESTED (proposals, recommendations) or LIMITATION." />
      <DemoNotice project={project} />
      <Card title="Generate a report" className="mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[16rem] flex-1"><Field label="Title (optional)"><input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} placeholder={`QA report — ${project.name}`} maxLength={300} /></Field></div>
          <Field label="Test run">
            <Select value={runId} onChange={setRunId} options={[{ value: '', label: 'Latest run with results' }, ...(runs.data?.items ?? []).map((r) => ({ value: String(r.id), label: `#${r.id} · ${r.status}` }))]} />
          </Field>
          <Button variant="primary" icon={<FileText className="size-4" />} onClick={create} loading={active}>Generate</Button>
        </div>
        <div className="mt-3 space-y-2"><JobLine job={job} label="Report" />{err && <ErrorNote error={err} />}</div>
        <p className="mt-2 text-xs text-ink-400">Reports never include access tokens, credentials or full source files. Generated files are stored on the server; on ephemeral hosting they may need regenerating after a redeploy.</p>
      </Card>
      {reports.loading && !reports.data ? <Spinner /> : !reports.data?.length ? (
        <EmptyState icon={<FileText className="size-8" />} title="No reports yet">Generate a report to capture the current analysis and test results.</EmptyState>
      ) : (
        <Card padded={false} title="Previous reports">
          <ul>{reports.data.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 border-t border-ink-800 px-4 py-3 first:border-0">
              <FileText className="size-4 text-ink-400" />
              <div className="min-w-0 flex-1"><div className="truncate text-sm text-ink-100">{r.title}</div>
                <div className="truncate text-xs text-ink-400">{dateTime(r.created_at)}{r.run_id ? ` · run #${r.run_id}` : ' · no executed run'}{r.summary.verdict ? ` · ${r.summary.verdict}` : ''}</div></div>
              <StatusBadge status={r.status} />
              {r.status === 'ready' && <div className="flex gap-1">
                <Button size="sm" variant="ghost" icon={<ExternalLink className="size-3.5" />} onClick={() => view(r)}>View</Button>
                <Button size="sm" icon={<Download className="size-3.5" />} onClick={() => dl(r, 'pdf')}>PDF</Button>
                <Button size="sm" icon={<Download className="size-3.5" />} onClick={() => dl(r, 'html')}>HTML</Button>
              </div>}
            </li>
          ))}</ul>
        </Card>
      )}
    </>
  );
}
