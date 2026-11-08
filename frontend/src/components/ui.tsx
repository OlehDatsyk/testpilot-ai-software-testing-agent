import { useEffect, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, CircleDashed, Info, Loader2, X, XCircle } from 'lucide-react';
import { cx } from '../utils/format';

// --- Button -----------------------------------------------------------------------------
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
export function Button({ variant = 'secondary', size = 'md', loading, icon, children, className, disabled, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: 'sm' | 'md'; loading?: boolean; icon?: ReactNode }) {
  const v = {
    primary: 'bg-accent-500 text-ink-950 hover:bg-accent-400 font-semibold',
    secondary: 'bg-ink-800 text-ink-100 border border-ink-600 hover:bg-ink-700',
    ghost: 'text-ink-300 hover:text-ink-100 hover:bg-ink-800',
    danger: 'bg-rose-500/10 text-rose-300 border border-rose-500/30 hover:bg-rose-500/20',
  }[variant];
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx('inline-flex items-center justify-center gap-2 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-accent-400',
        size === 'sm' ? 'h-8 px-2.5 text-xs' : 'h-9 px-3.5 text-sm', v, className)}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

// --- Layout primitives --------------------------------------------------------------------
export function Card({ title, actions, children, className, padded = true, subtitle }:
  { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; padded?: boolean }) {
  return (
    <section className={cx('rounded-lg border border-ink-700 bg-ink-900', className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-ink-700 px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-ink-100">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-400">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={padded ? 'p-4' : ''}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-white">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-ink-300">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'good' | 'bad' | 'warn' }) {
  const color = tone === 'good' ? 'text-emerald-300' : tone === 'bad' ? 'text-rose-300' : tone === 'warn' ? 'text-amber-300' : 'text-white';
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-900 px-4 py-3">
      <div className="text-xs font-medium text-ink-400">{label}</div>
      <div className={cx('mt-1 text-2xl font-semibold tabular-nums', color)}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-ink-400">{hint}</div>}
    </div>
  );
}

// --- Badges -------------------------------------------------------------------------------
export function Badge({ children, tone = 'neutral', className, title }: { children: ReactNode; tone?: 'neutral' | 'accent' | 'good' | 'bad' | 'warn' | 'violet'; className?: string; title?: string }) {
  const t = {
    neutral: 'bg-ink-700/60 text-ink-200 border-ink-600',
    accent: 'bg-accent-500/10 text-accent-300 border-accent-500/30',
    good: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
    bad: 'bg-rose-500/10 text-rose-300 border-rose-500/30',
    warn: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
    violet: 'bg-violet-500/10 text-violet-300 border-violet-500/30',
  }[tone];
  return <span title={title} className={cx('inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-medium', t, className)}>{children}</span>;
}

const SEV_TONE = { critical: 'bad', high: 'bad', medium: 'warn', low: 'neutral', info: 'neutral' } as const;
export function SeverityBadge({ severity }: { severity: string }) {
  const tone = SEV_TONE[severity as keyof typeof SEV_TONE] ?? 'neutral';
  return <Badge tone={tone} className={severity === 'critical' ? 'uppercase' : 'capitalize'}>{severity}</Badge>;
}

const STATUS: Record<string, { tone: 'neutral' | 'accent' | 'good' | 'bad' | 'warn' | 'violet'; label: string; live?: boolean }> = {
  queued: { tone: 'neutral', label: 'Queued', live: true },
  preparing: { tone: 'accent', label: 'Preparing', live: true },
  running: { tone: 'accent', label: 'Running', live: true },
  importing: { tone: 'accent', label: 'Importing', live: true },
  analysing: { tone: 'accent', label: 'Analysing', live: true },
  succeeded: { tone: 'good', label: 'Succeeded' },
  passed: { tone: 'good', label: 'Passed' },
  ready: { tone: 'good', label: 'Ready' },
  failed: { tone: 'bad', label: 'Failed' },
  error: { tone: 'bad', label: 'Error' },
  partially_passed: { tone: 'warn', label: 'Partially passed' },
  timed_out: { tone: 'warn', label: 'Timed out' },
  cancelled: { tone: 'neutral', label: 'Cancelled' },
  execution_unavailable: { tone: 'violet', label: 'Execution unavailable' },
  infrastructure_error: { tone: 'bad', label: 'Infrastructure error' },
  skipped: { tone: 'neutral', label: 'Skipped' },
  new: { tone: 'neutral', label: 'New' },
  proposed: { tone: 'accent', label: 'Awaiting review' },
  approved: { tone: 'good', label: 'Approved' },
  rejected: { tone: 'neutral', label: 'Rejected' },
  open: { tone: 'warn', label: 'Open' },
  accepted: { tone: 'accent', label: 'Accepted' },
  false_positive: { tone: 'neutral', label: 'False positive' },
  resolved: { tone: 'good', label: 'Resolved' },
  in_progress: { tone: 'accent', label: 'In progress' },
  wont_fix: { tone: 'neutral', label: "Won't fix" },
};
export function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? { tone: 'neutral' as const, label: status };
  return (
    <Badge tone={s.tone}>
      {s.live && <span className="pulse-dot size-1.5 rounded-full bg-current" />}
      {s.label}
    </Badge>
  );
}

export function ResultIcon({ status }: { status: string }) {
  if (status === 'passed') return <CheckCircle2 className="size-4 text-emerald-400" aria-label="passed" />;
  if (status === 'failed' || status === 'error') return <XCircle className="size-4 text-rose-400" aria-label={status} />;
  return <CircleDashed className="size-4 text-ink-400" aria-label={status} />;
}

// --- Feedback -------------------------------------------------------------------------------
export function Spinner({ label }: { label?: string }) {
  return <div className="flex items-center gap-2 py-8 text-sm text-ink-300"><Loader2 className="size-4 animate-spin" />{label ?? 'Loading…'}</div>;
}

export function ErrorNote({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-2 rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <div className="flex-1">{error}</div>
      {onRetry && <button onClick={onRetry} className="text-xs underline">Retry</button>}
    </div>
  );
}

export function Notice({ children, tone = 'info', className }: { children: ReactNode; tone?: 'info' | 'warn' | 'violet'; className?: string }) {
  const t = { info: 'border-accent-500/25 bg-accent-500/5 text-ink-200', warn: 'border-amber-500/30 bg-amber-500/5 text-amber-100', violet: 'border-violet-500/30 bg-violet-500/5 text-violet-100' }[tone];
  return <div className={cx('flex items-start gap-2 rounded-md border px-3 py-2 text-sm', t, className)}><Info className="mt-0.5 size-4 shrink-0 opacity-80" /><div>{children}</div></div>;
}

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-ink-600 px-6 py-12 text-center">
      {icon && <div className="mb-3 text-ink-400">{icon}</div>}
      <h3 className="text-sm font-semibold text-ink-100">{title}</h3>
      {children && <div className="mt-1 max-w-md text-sm text-ink-400">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

// --- Forms -------------------------------------------------------------------------------------
export const inputCls = 'h-9 w-full rounded-md border border-ink-600 bg-ink-850 px-3 text-sm text-ink-100 placeholder:text-ink-400 focus:border-accent-500 focus:outline-none';

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-ink-300">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-ink-400">{hint}</span>}
    </label>
  );
}

export function Select({ value, onChange, options, className, ariaLabel }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; className?: string; ariaLabel?: string }) {
  return (
    <select aria-label={ariaLabel} value={value} onChange={(e) => onChange(e.target.value)} className={cx(inputCls.replace('w-full ', ''), 'pr-8', className)}>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

// --- Modal ------------------------------------------------------------------------------------
export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-[8vh]" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => e.stopPropagation()}
        className={cx('w-full rounded-lg border border-ink-600 bg-ink-900 shadow-2xl', wide ? 'max-w-4xl' : 'max-w-lg')}>
        <div className="flex items-center justify-between border-b border-ink-700 px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 text-ink-400 hover:bg-ink-800 hover:text-ink-100"><X className="size-4" /></button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

// --- Tabs ---------------------------------------------------------------------------------------
export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div role="tablist" className="mb-4 flex gap-1 overflow-x-auto border-b border-ink-700">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cx('-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors',
            value === t.id ? 'border-accent-400 text-white' : 'border-transparent text-ink-400 hover:text-ink-200')}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function CodeBlock({ code, maxHeight = 420, className }: { code: string; maxHeight?: number; className?: string }) {
  return (
    <pre className={cx('code overflow-auto rounded-md border border-ink-700 bg-ink-950 p-3 text-ink-200', className)} style={{ maxHeight }}>
      <code>{code}</code>
    </pre>
  );
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  return (
    <div className="flex items-center justify-end gap-2 pt-3 text-xs text-ink-400">
      <span>{(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total}</span>
      <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
      <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button>
    </div>
  );
}

/** Small, dependency-free Markdown renderer for assistant answers (bold, code, lists, headings). */
export function Markdown({ text }: { text: string }) {
  const blocks = text.split(/```/);
  return (
    <div className="space-y-2 text-sm leading-relaxed">
      {blocks.map((b, i) => i % 2 === 1
        ? <CodeBlock key={i} code={b.replace(/^\w*\n/, '')} maxHeight={300} />
        : b.split(/\n{2,}/).flatMap((para, j) => {
          // Group consecutive bullet lines into lists; other lines become paragraphs.
          const groups: { list: boolean; lines: string[] }[] = [];
          for (const l of para.split('\n').filter(Boolean)) {
            const isItem = /^\s*[-*]\s/.test(l);
            const last = groups[groups.length - 1];
            if (last && last.list === isItem) last.lines.push(l); else groups.push({ list: isItem, lines: [l] });
          }
          return groups.map((g, k) => g.list
            ? <ul key={`${i}-${j}-${k}`} className="list-disc space-y-1 pl-5">{g.lines.map((l, n) => <li key={n}>{inline(l.replace(/^\s*[-*]\s/, ''))}</li>)}</ul>
            : <p key={`${i}-${j}-${k}`}>{g.lines.map((l, n) => <span key={n}>{inline(l.replace(/^#+\s/, ''))}{n < g.lines.length - 1 && <br />}</span>)}</p>);
        }))}
    </div>
  );
}

function inline(s: string): ReactNode[] {
  // Italics only for _text_ bounded by non-word characters, so snake_case paths stay intact.
  const parts = s.split(/(\*\*[^*]+\*\*|`[^`]+`|(?<![\w])_[^_\n]+_(?![\w]))/g);
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**')) return <strong key={i} className="font-semibold text-white">{p.slice(2, -2)}</strong>;
    if (p.startsWith('`') && p.endsWith('`')) return <code key={i} className="rounded bg-ink-800 px-1 py-0.5 font-mono text-[12px] text-accent-300">{p.slice(1, -1)}</code>;
    if (p.startsWith('_') && p.endsWith('_') && p.length > 2) return <em key={i} className="text-ink-300">{p.slice(1, -1)}</em>;
    return <span key={i}>{p}</span>;
  });
}
