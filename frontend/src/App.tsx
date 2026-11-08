import { Navigate, Route, Routes } from 'react-router-dom';
import { useApp } from './hooks/AppContext';
import AppLayout from './layouts/AppLayout';
import { Spinner } from './components/ui';
import AuthPage from './pages/AuthPage';
import OverviewPage from './pages/OverviewPage';
import ProjectsPage from './pages/ProjectsPage';
import AnalysisPage from './pages/AnalysisPage';
import GenerationPage from './pages/GenerationPage';
import RunsPage from './pages/RunsPage';
import RunDetailPage from './pages/RunDetailPage';
import ComparePage from './pages/ComparePage';
import BugsPage from './pages/BugsPage';
import CoveragePage from './pages/CoveragePage';
import AssistantPage from './pages/AssistantPage';
import ReportsPage from './pages/ReportsPage';
import SettingsPage from './pages/SettingsPage';

function Protected({ children }: { children: JSX.Element }) {
  const { me, authReady } = useApp();
  if (!authReady) return <div className="p-8"><Spinner /></div>;
  return me ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<AuthPage mode="login" />} />
      <Route path="/register" element={<AuthPage mode="register" />} />
      <Route element={<Protected><AppLayout /></Protected>}>
        <Route index element={<OverviewPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="analysis" element={<AnalysisPage />} />
        <Route path="generation" element={<GenerationPage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="runs/compare/:base/:head" element={<ComparePage />} />
        <Route path="runs/:id" element={<RunDetailPage />} />
        <Route path="bugs" element={<BugsPage />} />
        <Route path="coverage" element={<CoveragePage />} />
        <Route path="assistant" element={<AssistantPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
