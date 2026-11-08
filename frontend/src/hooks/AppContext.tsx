import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, setUnauthorizedHandler, tokenStore } from '../services/api';
import type { Capabilities, Me, Page, Project } from '../types/api';

interface AppState {
  me: Me | null;
  authReady: boolean;
  login: (token: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<void>;
  projects: Project[];
  refreshProjects: () => Promise<void>;
  projectId: number | null;
  setProjectId: (id: number | null) => void;
  project: Project | null;
  caps: Capabilities | null;
}

const Ctx = createContext<AppState | null>(null);
const PROJECT_KEY = 'testpilot.project';

export function AppProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [projectId, setProjectIdState] = useState<number | null>(() => {
    try { const v = localStorage.getItem(PROJECT_KEY); return v ? Number(v) : null; } catch { return null; }
  });

  const setProjectId = useCallback((id: number | null) => {
    setProjectIdState(id);
    try { if (id) localStorage.setItem(PROJECT_KEY, String(id)); else localStorage.removeItem(PROJECT_KEY); } catch { /* ignore */ }
  }, []);

  const refreshMe = useCallback(async () => {
    if (!tokenStore.get()) { setMe(null); setAuthReady(true); return; }
    try { setMe(await api.get<Me>('/api/auth/me')); } catch { tokenStore.clear(); setMe(null); }
    setAuthReady(true);
  }, []);

  const refreshProjects = useCallback(async () => {
    if (!tokenStore.get()) return;
    try {
      const page = await api.get<Page<Project>>('/api/projects', { page_size: 200 });
      setProjects(page.items);
    } catch { /* surfaced on pages */ }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => { tokenStore.clear(); setMe(null); });
    void refreshMe();
    api.get<Capabilities>('/api/system/capabilities').then(setCaps).catch(() => setCaps(null));
  }, [refreshMe]);

  useEffect(() => { if (me) void refreshProjects(); }, [me, refreshProjects]);

  useEffect(() => {
    if (!projects.length) return;
    if (!projectId || !projects.some((p) => p.id === projectId)) setProjectId(projects[0].id);
  }, [projects, projectId, setProjectId]);

  const login = useCallback(async (token: string) => { tokenStore.set(token); await refreshMe(); }, [refreshMe]);
  const logout = useCallback(async () => {
    try { await api.post('/api/auth/logout'); } catch { /* token may already be invalid */ }
    tokenStore.clear(); setMe(null); setProjects([]);
  }, []);

  const project = useMemo(() => projects.find((p) => p.id === projectId) ?? null, [projects, projectId]);

  const value = { me, authReady, login, logout, refreshMe, projects, refreshProjects, projectId, setProjectId, project, caps };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useApp outside AppProvider');
  return v;
}
