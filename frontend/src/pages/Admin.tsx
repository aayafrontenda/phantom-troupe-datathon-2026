import { Plus, Send, User } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import { useAuth } from '../auth';
import { Page, PageHeader, Stat, StatStrip } from '../components/page';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardHeader, CardTitle } from '../components/ui/card';
import { chipVariants } from '../components/ui/chip';
import { DialogBody, DialogFooter, DialogTitle } from '../components/ui/dialog';
import { Input, Label, PasswordInput } from '../components/ui/input';
import { Select } from '../components/ui/select';
import { useI18n } from '../i18n';
import { useCameras } from '../lib/cameras';
import { cn } from '../lib/utils';
import type { AdminUser } from '../types';
import { fmtDate, useUi } from '../ui';

interface Stats { jobs: { done: number; total: number }; alerts: { open: number }; uptime_sec: number; cameras: { id: string; name: string; status: string }[] }

const th = 'px-4 py-3 text-left text-xs font-semibold text-muted-foreground';
const td = 'md:px-4 md:py-3.5 md:align-middle';
const ROLE_BADGE = { admin: 'accent', supervisor: 'info', operator: 'muted' } as const;

export default function AdminPage() {
  const { t, locale } = useI18n();
  const { me } = useAuth();
  const { modal, toast } = useUi();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const { cams } = useCameras();

  const load = useCallback(async () => {
    try { setUsers((await api<{ users: AdminUser[] }>('/ui/api/users')).users); } catch (e) { toast((e as Error).message, 'err'); }
    try { setStats(await api<Stats>('/ui/api/stats')); } catch { /* ignore */ }
  }, [toast]);
  useEffect(() => { load(); }, [load]);

  const userDialog = (u?: AdminUser) => modal<Partial<AdminUser> & { password?: string; all_cameras?: boolean }>(close => {
    const v: Record<string, unknown> = { login: u?.login || '', name: u?.name || '', role: u?.role || 'operator', password: '', all_cameras: !u || u.camera_ids == null, camera_ids: u?.camera_ids || [] };
    return (
      <form onSubmit={e => { e.preventDefault(); close(v as never); }}>
        <DialogTitle>{u ? t('adm.edit') : t('adm.addUser')}</DialogTitle>
        <DialogBody>
          <div className="grid gap-3 sm:grid-cols-2">
            <div><Label htmlFor="u-login">{t('adm.login')}</Label><Input id="u-login" defaultValue={String(v.login)} disabled={!!u} required pattern="[A-Za-z0-9_.@\-]+" onChange={e => { v.login = e.target.value; }} autoFocus={!u} /></div>
            <div><Label htmlFor="u-name">{t('adm.name')}</Label><Input id="u-name" defaultValue={String(v.name)} required onChange={e => { v.name = e.target.value; }} /></div>
            <div><Label htmlFor="u-role">{t('adm.role')}</Label><Select id="u-role" defaultValue={String(v.role)} onChange={e => { v.role = e.target.value; }}>
              {['operator', 'supervisor', 'admin'].map(r => <option key={r} value={r}>{t(`role.${r}`)}</option>)}</Select></div>
            <div><Label htmlFor="u-pw">{u ? t('adm.newPassword') : t('adm.password')}</Label><PasswordInput id="u-pw" autoComplete="new-password" minLength={4} required={!u} onChange={e => { v.password = e.target.value; }} showLabel={t('pw.show')} hideLabel={t('pw.hide')} /></div>
            <div className="sm:col-span-2"><Label htmlFor="u-cams">{t('adm.cams')}</Label>
              <Select id="u-cams" defaultValue={v.all_cameras ? 'all' : 'some'} onChange={e => { v.all_cameras = e.target.value === 'all'; }}>
                <option value="all">{t('adm.allCams')}</option><option value="some">{t('adm.someCams')}</option></Select>
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {cams.map(c => (
                  <label key={c.id} className={chipVariants({ on: false })}>
                    <input type="checkbox" className="accent-primary" defaultChecked={(v.camera_ids as string[]).includes(c.id)}
                      onChange={e => { const ids = new Set(v.camera_ids as string[]); e.target.checked ? ids.add(c.id) : ids.delete(c.id); v.camera_ids = [...ids]; }} /> {c.name}
                  </label>
                ))}
              </div>
            </div>
          </div>
        </DialogBody>
        <DialogFooter><Button type="button" variant="secondary" size="sm" onClick={() => close(null)}>{t('cancel')}</Button><Button type="submit" size="sm">{t('save')}</Button></DialogFooter>
      </form>
    );
  }, true);

  const addUser = async () => {
    const v = await userDialog(); if (!v) return;
    try {
      await api('/ui/api/users', { method: 'POST', json: { login: v.login, password: v.password, role: v.role, name: v.name, camera_ids: v.all_cameras ? null : v.camera_ids } });
      toast(t('adm.created')); load();
    } catch (e) { toast((e as Error).message, 'err'); }
  };
  const editUser = async (u: AdminUser) => {
    const v = await userDialog(u); if (!v) return;
    const body: Record<string, unknown> = { name: v.name, role: v.role };
    if (v.password) body.password = v.password;
    if (v.all_cameras) body.all_cameras = true; else body.camera_ids = v.camera_ids;
    try { await api(`/ui/api/users/${u.id}`, { method: 'PATCH', json: body }); toast(t('adm.saved')); load(); }
    catch (e) { toast((e as Error).message, 'err'); }
  };
  const unlinkTg = async (u: AdminUser) => {
    try { await api(`/ui/api/users/${u.id}`, { method: 'PATCH', json: { unlink_telegram: true } }); toast(t('tg.unlinked')); load(); }
    catch (e) { toast((e as Error).message, 'err'); }
  };
  const toggleUser = async (u: AdminUser) => {
    try { await api(`/ui/api/users/${u.id}`, { method: 'PATCH', json: { active: !u.active } }); load(); }
    catch (e) { toast((e as Error).message, 'err'); }
  };
  const retention = me?.features.retention_days || 0;

  return (
    <Page wide>
      <PageHeader title={t('adm.title')} lead={t('adm.lead')} actions={<Button onClick={addUser}><Plus />{t('adm.addUser')}</Button>} />
      <StatStrip cols={5}>
        <Stat value={stats?.jobs.done ?? '-'} label={t('adm.jobs')} />
        <Stat tone="warn" value={stats?.alerts.open ?? '-'} label={t('adm.alerts')} />
        <Stat tone="ok" value={`${cams.filter(c => c.state?.status === 'online').length}/${cams.length}`} label={t('adm.cameras')} />
        <Stat small value={me?.analyzer} label={`${t('adm.analyzer')} · ${me?.version}`} />
        <Stat small value={retention ? t('adm.days', { n: retention }) : t('adm.forever')} label={t('adm.retention')} />
      </StatStrip>
      <div>
        <Card>
          <CardHeader className="border-b border-border px-4 py-3.5"><CardTitle className="text-base">{t('adm.users')}</CardTitle></CardHeader>
          <table className="w-full text-sm">
            <thead className="hidden border-b border-border md:table-header-group">
              <tr><th className={th}>{t('adm.login')}</th><th className={th}>{t('adm.role')}</th><th className={th}>{t('adm.cams')}</th><th className={th}>{t('adm.lastLogin')}</th><th className={th}><span className="sr-only">{t('adm.edit')}</span></th></tr>
            </thead>
            <tbody className="divide-y divide-border">
              {users.map(u => (
                <tr key={u.id} className={cn('grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 px-4 py-3 md:table-row md:p-0', !u.active && 'opacity-55')}>
                  <td className={cn(td, 'col-start-1')}>
                    <div className="flex min-w-0 items-center gap-3">
                      <span className="hidden size-9 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground md:grid"><User className="size-4" /></span>
                      <div className="min-w-0"><b className="block truncate font-semibold">{u.name}</b>
                        <small className="text-xs text-muted-foreground">{u.login}{!u.active && <> · {t('adm.inactive')}</>}
                          {u.telegram && <> · <span className="inline-flex items-center gap-1 text-info" title={t('tg.title')}><Send className="size-[13px]" />{u.telegram.username ? '@' + u.telegram.username : 'Telegram'}</span></>}</small></div>
                    </div>
                  </td>
                  <td className={cn(td, 'col-start-1')}><Badge variant={ROLE_BADGE[u.role]}>{t(`role.${u.role}`)}</Badge></td>
                  <td className={cn(td, 'col-start-1 text-[13px] text-muted-foreground')}>{u.camera_ids == null ? t('adm.allCams') : u.camera_ids.map(id => cams.find(c => c.id === id)?.name || id).join(', ') || '-'}</td>
                  <td className={cn(td, 'col-start-1 text-[13px] text-muted-foreground')}>{u.last_login_at ? fmtDate(u.last_login_at, locale) : t('adm.never')}</td>
                  <td className={cn(td, 'col-start-2 row-span-4 row-start-1 self-center')}>
                    <div className="flex flex-col items-end gap-1 md:flex-row md:items-center md:justify-end">
                      <Button size="xs" variant="secondary" onClick={() => editUser(u)}>{t('adm.edit')}</Button>
                      {u.telegram && <Button size="xs" variant="ghost" onClick={() => unlinkTg(u)}>{t('adm.tgUnlink')}</Button>}
                      <Button size="xs" variant={u.active ? 'destructive' : 'success'} onClick={() => toggleUser(u)}>{t(u.active ? 'adm.disable' : 'adm.enable')}</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <p className="mt-3.5 text-[13px] text-muted-foreground"><b className="font-semibold text-foreground">{t('adm.apiKey')}</b> - {t('adm.apiKeyHint')}</p>
      </div>
    </Page>
  );
}
