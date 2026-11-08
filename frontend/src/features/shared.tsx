import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { FolderGit2 } from 'lucide-react';
import { useApp } from '../hooks/AppContext';
import { api } from '../services/api';
import type { Job, Project } from '../types/api';
import { Button, EmptyState, StatusBadge } from '../components/ui';

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled', 'timed_out', 'execution_unavailable', 'infrastructure_error']);

/** Polls a background job until it reaches a terminal state. Shows only real recorded states. */
export function useJob(onDone?: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const cb = useRef(onDone);
  cb.current = onDone;
  useEffect(() => {
    if (!job || TERMINAL.has(job.status)) return;
    const t = setTimeout(async () => {
      try {
        const j = await api.get<Job>(`/api/jobs/${job.id}`);
        setJob(j);
        if (TERMINAL.has(j.status)) cb.current?.(j);
      } catch { /* keep polling */ }
    }, 1500);
    return () => clearTimeout(t);
  }, [job]);
  return { job, track: setJob, active: !!job && !TERMINAL.has(job.status) };
}

export function JobLine({ job, label }: { job: Job | null; label: string }) {
  if (!job) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-ink-300">
      <span>{label} job #{job.id}</span>
      <StatusBadge status={job.status} />
      {job.error && <span className="text-rose-300">{job.error}</span>}
    </div>
  );
}

/** Renders children with the selected project, or a helpful empty state. */
export function WithProject({ children }: { children: (p: Project) => ReactNode }) {
  const { project, projects } = useApp();
  if (!project) {
    return (
      <EmptyState icon={<FolderGit2 className="size-8" />} title={projects.length ? 'Select a project' : 'No projects yet'}
        action={<Link to="/projects"><Button variant="primary">Go to Projects</Button></Link>}>
        {projects.length ? 'Choose a project in the top bar.' : 'Create a project, connect a GitHub repository, upload an archive or load the clearly-labelled demo project.'}
      </EmptyState>
    );
  }
  return <>{children(project)}</>;
}

export function DemoNotice({ project }: { project: Project }) {
  if (!project.is_demo) return null;
  return (
    <div className="mb-4 rounded-md border border-violet-500/30 bg-violet-500/5 px-3 py-2 text-xs text-violet-200">
      <b>Demo project.</b> Code written specifically for TestPilot with deliberate defects — not a real customer repository. Results shown here come from the same analysis and execution pipeline as any other project.
    </div>
  );
}
