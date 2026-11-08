import { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import {
  Bot, Bug, ChevronDown, FileText, FlaskConical, FolderGit2, Gauge, LayoutDashboard, LogOut, Menu, PlayCircle,
  ScanSearch, Settings, X,
} from 'lucide-react';
import { useApp } from '../hooks/AppContext';
import { cx } from '../utils/format';
import { Badge } from '../components/ui';

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/projects', label: 'Projects', icon: FolderGit2 },
  { to: '/analysis', label: 'Repository Analysis', icon: ScanSearch },
  { to: '/generation', label: 'Test Generation', icon: FlaskConical },
  { to: '/runs', label: 'Test Runs', icon: PlayCircle },
  { to: '/bugs', label: 'Bug Reports', icon: Bug },
  { to: '/coverage', label: 'Coverage', icon: Gauge },
  { to: '/assistant', label: 'AI Testing Assistant', icon: Bot },
  { to: '/reports', label: 'Reports', icon: FileText },
  { to: '/settings', label: 'Settings', icon: Settings },
];

export function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="size-7" aria-hidden><rect width="32" height="32" rx="7" fill="#141e33" /><path d="M8 22 L16 8 L24 22 L16 18 Z" fill="#22d3ee" /></svg>
      <div className="leading-tight">
        <div className="text-sm font-semibold text-white">TestPilot AI</div>
        <div className="text-[10px] uppercase tracking-wider text-ink-400">QA Platform</div>
      </div>
    </div>
  );
}

export default function AppLayout() {
  const { me, logout, projects, projectId, setProjectId, project, caps } = useApp();
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const nav = useNavigate();
  const ws = me?.workspaces[0];

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center justify-between px-4"><Logo />
        <button className="lg:hidden" onClick={() => setOpen(false)} aria-label="Close menu"><X className="size-5 text-ink-300" /></button>
      </div>
      <div className="px-3 pb-3">
        <div className="rounded-md border border-ink-700 bg-ink-850 px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider text-ink-400">Workspace</div>
          <div className="truncate text-sm text-ink-100">{ws?.name ?? '—'}</div>
        </div>
      </div>
      <nav className="flex-1 space-y-0.5 overflow-y-auto px-3" aria-label="Main">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}
            className={({ isActive }) => cx('flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors',
              isActive ? 'bg-ink-800 text-white' : 'text-ink-300 hover:bg-ink-850 hover:text-ink-100')}>
            {({ isActive }) => <><Icon className={cx('size-4', isActive ? 'text-accent-400' : 'text-ink-400')} />{label}</>}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-ink-700 p-3 text-[11px] text-ink-400">
        <div className="flex items-center justify-between"><span>Execution</span>
          <span className={caps?.execution.available ? 'text-emerald-300' : 'text-violet-300'}>{caps ? (caps.execution.available ? caps.execution.provider : 'unavailable') : '…'}</span>
        </div>
        <div className="mt-1 flex items-center justify-between"><span>AI provider</span>
          <span className={caps?.ai.configured ? 'text-emerald-300' : 'text-ink-300'}>{caps ? (caps.ai.configured ? caps.ai.provider : 'not configured') : '…'}</span>
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 border-r border-ink-700 bg-ink-900 lg:block">{sidebar}</aside>
      {open && <div className="fixed inset-0 z-40 bg-black/60 lg:hidden" onClick={() => setOpen(false)}><aside className="h-full w-64 bg-ink-900" onClick={(e) => e.stopPropagation()}>{sidebar}</aside></div>}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-ink-700 bg-ink-900/80 px-4 backdrop-blur">
          <button className="lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu"><Menu className="size-5 text-ink-300" /></button>
          <div className="flex min-w-0 items-center gap-2">
            <span className="hidden text-xs text-ink-400 sm:inline">Project</span>
            <select aria-label="Current project" value={projectId ?? ''} onChange={(e) => setProjectId(Number(e.target.value) || null)}
              className="h-8 max-w-[16rem] truncate rounded-md border border-ink-600 bg-ink-850 px-2 text-sm text-ink-100 focus:border-accent-500 focus:outline-none">
              {!projects.length && <option value="">No projects yet</option>}
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            {project?.is_demo && <Badge tone="violet" title="Demonstration data — not a real customer repository">DEMO</Badge>}
          </div>
          <div className="ml-auto relative">
            <button onClick={() => setMenu((m) => !m)} className="flex items-center gap-2 rounded-md px-2 py-1 text-sm text-ink-200 hover:bg-ink-800" aria-haspopup="menu" aria-expanded={menu}>
              <span className="flex size-7 items-center justify-center rounded-full bg-accent-500/15 text-xs font-semibold text-accent-300">{me?.user.name.slice(0, 1).toUpperCase()}</span>
              <span className="hidden max-w-[10rem] truncate sm:inline">{me?.user.name}</span>
              <ChevronDown className="size-4 text-ink-400" />
            </button>
            {menu && (
              <div role="menu" className="absolute right-0 z-30 mt-1 w-56 rounded-md border border-ink-600 bg-ink-900 py-1 shadow-xl" onMouseLeave={() => setMenu(false)}>
                <div className="border-b border-ink-700 px-3 py-2 text-xs text-ink-400">{me?.user.email}</div>
                <button role="menuitem" className="flex w-full items-center gap-2 px-3 py-2 text-sm text-ink-200 hover:bg-ink-800" onClick={() => { setMenu(false); nav('/settings'); }}><Settings className="size-4" />Settings</button>
                <button role="menuitem" className="flex w-full items-center gap-2 px-3 py-2 text-sm text-rose-300 hover:bg-ink-800" onClick={() => { void logout(); nav('/login'); }}><LogOut className="size-4" />Sign out</button>
              </div>
            )}
          </div>
        </header>
        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6"><Outlet /></div>
        </main>
      </div>
    </div>
  );
}
