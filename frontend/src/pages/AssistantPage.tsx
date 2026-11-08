import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Bot, Plus, Send, User } from 'lucide-react';
import { api } from '../services/api';
import { useApp } from '../hooks/AppContext';
import { errorMessage, useAsync } from '../hooks/useAsync';
import type { ChatMessage, Project } from '../types/api';
import { Badge, Button, ErrorNote, Markdown, Notice, PageHeader } from '../components/ui';
import { DemoNotice, WithProject } from '../features/shared';
import { cx, timeAgo } from '../utils/format';

const SUGGESTIONS = [
  'Explain the architecture of this project',
  'Which functions should have more tests?',
  'Summarise the latest test run',
  'Why did the tests fail?',
  'Which files have no test coverage?',
  'What should I test before releasing?',
  'List the open findings',
];

export default function AssistantPage() {
  return <WithProject>{(p) => <AssistantView key={p.id} project={p} />}</WithProject>;
}

function AssistantView({ project }: { project: Project }) {
  const { caps } = useApp();
  const convs = useAsync(() => api.get<{ id: number; title: string; created_at: string }[]>(`/api/projects/${project.id}/conversations`), [project.id]);
  const [convId, setConvId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, busy]);

  async function openConv(id: number) {
    setConvId(id);
    try { setMessages(await api.get<ChatMessage[]>(`/api/projects/${project.id}/conversations/${id}/messages`)); } catch (e) { setErr(errorMessage(e)); }
  }
  async function send(message: string) {
    if (!message.trim()) return;
    setBusy(true); setErr(null); setText('');
    const optimistic: ChatMessage = { id: -Date.now(), role: 'user', content: message, provider: null, sources: [], created_at: new Date().toISOString() };
    setMessages((m) => [...m, optimistic]);
    try {
      const r = await api.post<{ conversation_id: number; message: ChatMessage }>(`/api/projects/${project.id}/assistant`, { message, conversation_id: convId });
      setMessages((m) => [...m, r.message]);
      if (!convId) { setConvId(r.conversation_id); void convs.reload(); }
    } catch (e) { setErr(errorMessage(e)); setMessages((m) => m.filter((x) => x.id !== optimistic.id)); setText(message); }
    finally { setBusy(false); }
  }
  function submit(e: FormEvent) { e.preventDefault(); void send(text); }

  return (
    <>
      <PageHeader title="AI Testing Assistant" description="Answers are grounded in this project’s stored analysis, findings, test results and coverage. If the data isn’t there, the assistant says so." />
      <DemoNotice project={project} />
      {!caps?.ai.configured && <Notice className="mb-4">No AI provider is configured. The assistant answers common questions deterministically from stored data (architecture, failures, coverage, findings, release checklist). Configure <code className="font-mono">AI_PROVIDER</code> on the backend for free-form answers.</Notice>}
      <div className="grid gap-4 lg:grid-cols-[14rem_1fr]">
        <aside className="space-y-1">
          <Button size="sm" className="mb-2 w-full" icon={<Plus className="size-3.5" />} onClick={() => { setConvId(null); setMessages([]); }}>New conversation</Button>
          {convs.data?.map((c) => (
            <button key={c.id} onClick={() => openConv(c.id)} className={cx('block w-full truncate rounded px-2 py-1.5 text-left text-sm', convId === c.id ? 'bg-ink-800 text-white' : 'text-ink-300 hover:bg-ink-850')}>
              {c.title}<div className="text-[11px] text-ink-400">{timeAgo(c.created_at)}</div>
            </button>
          ))}
        </aside>
        <div className="flex min-h-[60vh] flex-col rounded-lg border border-ink-700 bg-ink-900">
          <div className="flex-1 space-y-4 overflow-y-auto p-4">
            {messages.length === 0 && (
              <div className="py-6">
                <p className="mb-3 text-sm text-ink-400">Try one of these:</p>
                <div className="flex flex-wrap gap-2">{SUGGESTIONS.map((s) => <button key={s} onClick={() => send(s)} className="rounded-full border border-ink-600 px-3 py-1 text-xs text-ink-200 hover:border-accent-500 hover:text-white">{s}</button>)}</div>
              </div>
            )}
            {messages.map((m) => (
              <div key={m.id} className={cx('flex gap-3', m.role === 'user' && 'flex-row-reverse')}>
                <div className={cx('flex size-7 shrink-0 items-center justify-center rounded-full', m.role === 'user' ? 'bg-ink-700' : 'bg-accent-500/15 text-accent-300')}>{m.role === 'user' ? <User className="size-4" /> : <Bot className="size-4" />}</div>
                <div className={cx('max-w-[85%] rounded-lg px-3 py-2', m.role === 'user' ? 'bg-ink-800 text-ink-100' : 'border border-ink-700 bg-ink-850 text-ink-200')}>
                  {m.role === 'assistant' ? <Markdown text={m.content} /> : <p className="whitespace-pre-wrap text-sm">{m.content}</p>}
                  {m.role === 'assistant' && <div className="mt-2 flex flex-wrap gap-1"><Badge tone={m.provider?.startsWith('ai:') ? 'violet' : 'neutral'}>{m.provider === 'grounded-rules' ? 'answered from stored data' : m.provider}</Badge>{m.sources.map((s) => <Badge key={s}>{s}</Badge>)}</div>}
                </div>
              </div>
            ))}
            {busy && <div className="flex items-center gap-2 text-sm text-ink-400"><Bot className="size-4" />Thinking…</div>}
            <div ref={end} />
          </div>
          {err && <div className="px-4 pb-2"><ErrorNote error={err} /></div>}
          <form onSubmit={submit} className="flex gap-2 border-t border-ink-700 p-3">
            <input aria-label="Message" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask about this project…" maxLength={4000}
              className="h-10 flex-1 rounded-md border border-ink-600 bg-ink-850 px-3 text-sm focus:border-accent-500 focus:outline-none" />
            <Button type="submit" variant="primary" icon={<Send className="size-4" />} loading={busy} disabled={!text.trim()}>Send</Button>
          </form>
        </div>
      </div>
    </>
  );
}
