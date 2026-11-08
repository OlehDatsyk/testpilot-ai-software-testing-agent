import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../services/api';

export interface AsyncState<T> {
  data: T | undefined;
  error: string | null;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (d: T | undefined) => void;
}

/** Load data from the API; optional polling while `pollWhile(data)` is true. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], opts: { pollMs?: number; pollWhile?: (d: T | undefined) => boolean; skip?: boolean } = {}): AsyncState<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!opts.skip);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const alive = useRef(true);

  const reload = useCallback(async () => {
    if (opts.skip) { setLoading(false); return; }
    try {
      const d = await fnRef.current();
      if (alive.current) { setData(d); setError(null); }
    } catch (e) {
      if (alive.current) setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      if (alive.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, opts.skip]);

  useEffect(() => {
    alive.current = true;
    setLoading(!opts.skip);
    void reload();
    return () => { alive.current = false; };
  }, [reload, opts.skip]);

  useEffect(() => {
    if (!opts.pollMs || !opts.pollWhile || !opts.pollWhile(data)) return;
    const t = setTimeout(() => void reload(), opts.pollMs);
    return () => clearTimeout(t);
  }, [data, opts.pollMs, opts.pollWhile, reload]);

  return { data, error, loading, reload, setData };
}

export function errorMessage(e: unknown): string {
  return e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
}
