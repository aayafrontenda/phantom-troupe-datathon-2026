import { Upload } from 'lucide-react';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../i18n';
import { cn } from '../lib/utils';
import { useUi } from '../ui';

export interface UploadItem { key: string; name: string; sent: number; total: number }
interface Ctx {
  uploads: UploadItem[];
  local: Record<string, string>;
  pick: () => void;
  uploadFiles: (files: File[]) => void;
  version: number;
}
const C = createContext<Ctx | null>(null);

export function UploadProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const { toast } = useUi();
  const nav = useNavigate();
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [local, setLocal] = useState<Record<string, string>>({});
  const [version, setVersion] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  const uploadOne = useCallback((file: File, openAfter: boolean) => {
    const key = `u${Date.now()}${Math.random().toString(16).slice(2, 6)}`;
    setUploads(u => [...u, { key, name: file.name, sent: 0, total: file.size }]);
    const fd = new FormData();
    fd.append('file', file, file.name);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/ui/api/analyze');
    xhr.upload.onprogress = e => { if (e.lengthComputable) setUploads(u => u.map(x => x.key === key ? { ...x, sent: e.loaded } : x)); };
    xhr.onload = () => {
      setUploads(u => u.filter(x => x.key !== key));
      let body: { job_id?: string; detail?: string } = {};
      try { body = JSON.parse(xhr.responseText); } catch {}
      if (xhr.status !== 200 || !body.job_id) { toast(`${file.name}: ${body.detail || t('up.failed')}`, 'err'); setVersion(v => v + 1); return; }
      setLocal(l => ({ ...l, [body.job_id!]: URL.createObjectURL(file) }));
      setVersion(v => v + 1);
      if (openAfter) nav(`/checks/${body.job_id}`);
    };
    xhr.onerror = () => { setUploads(u => u.filter(x => x.key !== key)); toast(`${file.name}: ${t('up.network')}`, 'err'); };
    xhr.send(fd);
  }, [nav, t, toast]);

  const uploadFiles = useCallback((files: File[]) => {
    const ok = files.filter(f => /\.(mov|mp4|m4v)$/i.test(f.name));
    files.filter(f => !ok.includes(f)).forEach(f => toast(t('up.notVideo', { name: f.name }), 'err'));
    if (!ok.length) return;
    ok.forEach(f => uploadOne(f, ok.length === 1));
    if (!location.pathname.startsWith('/checks')) nav('/checks');
  }, [nav, t, toast, uploadOne]);

  const pick = useCallback(() => input.current?.click(), []);

  useEffect(() => {
    const over = (e: DragEvent) => e.preventDefault();
    const drop = (e: DragEvent) => {
      e.preventDefault();
      if ((e.target as HTMLElement)?.closest?.('[data-dropzone]')) return;
      if (e.dataTransfer?.files.length) uploadFiles([...e.dataTransfer.files]);
    };
    document.addEventListener('dragover', over);
    document.addEventListener('drop', drop);
    return () => { document.removeEventListener('dragover', over); document.removeEventListener('drop', drop); };
  }, [uploadFiles]);

  const value = useMemo(() => ({ uploads, local, pick, uploadFiles, version }), [uploads, local, pick, uploadFiles, version]);
  return (
    <C.Provider value={value}>
      {children}
      <input ref={input} type="file" accept=".mov,.mp4,.m4v,video/quicktime,video/mp4" multiple hidden
        onChange={e => { uploadFiles([...(e.target.files || [])]); e.target.value = ''; }} />
    </C.Provider>
  );
}

export function useUploads(): Ctx {
  const v = useContext(C);
  if (!v) throw new Error('useUploads outside provider');
  return v;
}

export function DropZone({ onPick, className }: { onPick: () => void; className?: string }) {
  const { t } = useI18n();
  const { uploadFiles } = useUploads();
  const [over, setOver] = useState(false);
  return (
    <div data-dropzone
      className={cn('flex cursor-pointer flex-wrap items-center gap-4 rounded-xl border border-dashed px-5 py-[18px] transition-colors sm:flex-nowrap',
        over ? 'border-primary bg-primary-soft' : 'border-border-strong bg-subtle hover:border-primary hover:bg-primary-soft', className)}
      onDragEnter={e => { e.preventDefault(); setOver(true); }} onDragOver={e => { e.preventDefault(); setOver(true); }}
      onDragLeave={e => { e.preventDefault(); setOver(false); }}
      onDrop={e => { e.preventDefault(); setOver(false); uploadFiles([...e.dataTransfer.files]); }}
      onClick={e => { if (!(e.target as HTMLElement).closest('button')) onPick(); }}>
      <span className="grid size-[42px] shrink-0 place-items-center rounded-[9px] border border-border bg-card text-primary"><Upload className="size-5" strokeWidth={1.7} /></span>
      <div><b className="block text-[15.5px] font-semibold text-foreground">{t('drop.title')}</b><small className="text-[13.5px] text-muted-foreground">{t('drop.hint')}</small></div>
    </div>
  );
}
