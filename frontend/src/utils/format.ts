export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ');
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—';
  const t = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z').getTime();
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 45) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  if (s < 86400 * 30) return `${Math.round(s / 86400)}d ago`;
  return new Date(t).toLocaleDateString();
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function pct(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? '—' : `${v.toFixed(digits)}%`;
}

export function seconds(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  return v < 1 ? `${Math.round(v * 1000)} ms` : `${v.toFixed(2)} s`;
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export const SEVERITIES = ['critical', 'high', 'medium', 'low', 'info'] as const;

export function humanize(s: string): string {
  return s.replace(/[_-]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
}

/** Pass rate over executed tests only; returns null when nothing executed (never 0% or 100% by default). */
export function passRate(passed: number, total: number): number | null {
  return total > 0 ? (100 * passed) / total : null;
}
