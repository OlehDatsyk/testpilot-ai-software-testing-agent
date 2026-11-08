import { useState, type FormEvent } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { ShieldCheck, FlaskConical, ScanSearch } from 'lucide-react';
import { api } from '../services/api';
import { useApp } from '../hooks/AppContext';
import { errorMessage } from '../hooks/useAsync';
import { Button, ErrorNote, Field, inputCls } from '../components/ui';
import { Logo } from '../layouts/AppLayout';

export default function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const { login, me } = useApp();
  const nav = useNavigate();
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (me) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<{ access_token: string }>(`/api/auth/${mode}`, mode === 'login' ? { email, password } : { email, name, password });
      await login(res.access_token);
      nav('/');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-full lg:grid-cols-2">
      <div className="hidden flex-col justify-between border-r border-ink-700 bg-ink-900 p-10 lg:flex">
        <Logo />
        <div className="max-w-md">
          <h1 className="text-2xl font-semibold text-white">Software quality, grounded in evidence.</h1>
          <p className="mt-3 text-sm text-ink-300">Analyse repositories, generate reviewable tests, execute them in an isolated sandbox, and report only what actually ran.</p>
          <ul className="mt-8 space-y-4 text-sm text-ink-200">
            <li className="flex gap-3"><ScanSearch className="size-5 text-accent-400" />Static analysis with exact source evidence</li>
            <li className="flex gap-3"><FlaskConical className="size-5 text-accent-400" />Test proposals that require human approval</li>
            <li className="flex gap-3"><ShieldCheck className="size-5 text-accent-400" />Execution isolated from application secrets</li>
          </ul>
        </div>
        <p className="text-xs text-ink-400">Generated tests are never reported as passed until they have executed.</p>
      </div>
      <div className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-sm space-y-4">
          <div className="lg:hidden"><Logo /></div>
          <div>
            <h2 className="text-lg font-semibold text-white">{mode === 'login' ? 'Sign in' : 'Create your account'}</h2>
            <p className="text-sm text-ink-400">{mode === 'login' ? 'Welcome back to TestPilot AI.' : 'A personal workspace is created automatically.'}</p>
          </div>
          {error && <ErrorNote error={error} />}
          {mode === 'register' && <Field label="Name"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} autoComplete="name" /></Field>}
          <Field label="Email"><input className={inputCls} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" /></Field>
          <Field label="Password" hint={mode === 'register' ? 'At least 10 characters, including a letter and a number.' : undefined}>
            <input className={inputCls} type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={mode === 'register' ? 10 : 1}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
          </Field>
          <Button type="submit" variant="primary" className="w-full" loading={busy}>{mode === 'login' ? 'Sign in' : 'Create account'}</Button>
          <p className="text-center text-sm text-ink-400">
            {mode === 'login' ? <>No account? <Link className="text-accent-300 hover:underline" to="/register">Register</Link></>
              : <>Already registered? <Link className="text-accent-300 hover:underline" to="/login">Sign in</Link></>}
          </p>
        </form>
      </div>
    </div>
  );
}
