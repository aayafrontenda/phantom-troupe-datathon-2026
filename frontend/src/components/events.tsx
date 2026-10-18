/* Shared live feed of findings (one SSE connection for the whole app): the header badge and the monitoring page use it. */
import { useEffect, useState } from 'react';
import { api } from '../api';
import type { FindingBrief } from '../types';

interface FeedState { items: FindingBrief[]; counts: Record<string, number>; loaded: boolean; error: string | null }
type Listener = (s: FeedState) => void;

let state: FeedState = { items: [], counts: {}, loaded: false, error: null };
const listeners = new Set<Listener>();
let es: EventSource | null = null;
let timer: number | null = null;
let refCount = 0;

function emit() { listeners.forEach(l => l(state)); }

async function reload() {
  try {
    const d = await api<{ findings: FindingBrief[]; counts: Record<string, number> }>('/ui/api/findings?limit=80', { silent401: true });
    state = { items: d.findings, counts: d.counts, loaded: true, error: null };
    emit();
  } catch (e) {
    // keep the previous list, but let the pages say the server is unreachable
    state = { ...state, error: (e as Error).message || 'error' };
    emit();
  }
}

function scheduleReload() {
  if (timer) return;
  timer = window.setTimeout(() => { timer = null; reload(); }, 400);
}

function connect() {
  if (es) return;
  try {
    es = new EventSource('/ui/api/findings/stream');
    ['finding', 'finding_update', 'finding_deleted'].forEach(ev => es!.addEventListener(ev, scheduleReload));
    es.onerror = () => { /* the browser reconnects; a poll covers the gap */ };
  } catch { es = null; }
}

function disconnect() {
  es?.close(); es = null;
}

export function useFeed(): FeedState {
  const [s, setS] = useState(state);
  useEffect(() => {
    listeners.add(setS);
    if (refCount++ === 0) { reload(); connect(); }
    const poll = setInterval(reload, 20000);
    return () => {
      listeners.delete(setS);
      clearInterval(poll);
      if (--refCount === 0) disconnect();
    };
  }, []);
  return s;
}

export function useOpenCount(): number {
  const { counts } = useFeed();
  return counts.pending || 0;
}

export function refreshFeed() { scheduleReload(); }
