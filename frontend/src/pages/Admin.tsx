import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import { useAuth } from '../auth';
import { useI18n } from '../i18n';
import type { AdminUser, Camera } from '../types';
import { fmtDate, Icon, useUi } from '../ui';
import { addCameraDialog, useCameras } from './Live';

interface Stats { jobs: { done: number; total: number }; alerts: { open: number }; uptime_sec: number; cameras: { id: string; name: string; status: string }[] }

export default function AdminPage() {
  const { t, locale } = useI18n();
  const { me } = useAuth();
  const { modal, confirm, toast } = useUi();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const { cams, refresh: refreshCams } = useCameras();

  const load = useCallback(async () => {
    try { setUsers((await api<{ users: AdminUser[] }>('/ui/api/users')).users); } catch (e) { toast((e as Error).message, 'err'); }
    try { setStats(await api<Stats>('/ui/api/stats')); } catch { /* ignore */ }
  }, [toast]);
  useEffect(() => { load(); }, [load]);

  const userDialog = (u?: AdminUser) => modal<Partial<AdminUser> & { password?: string; all_cameras?: boolean }>(close => {
    const v: Record<string, unknown> = { login: u?.login || '', name: u?.name || '', role: u?.role || 'operator', password: '', all_cameras: !u || u.camera_ids == null, camera_ids: u?.camera_ids || [] };
    return (
      <form onSubmit={e => { e.preventDefault(); close(v as never); }}>
        <h3>{u ? t('adm.edit') : t('adm.addUser')}</h3>
        <div className="form">
          <div className="form-grid">
            <div><label className="lbl">{t('adm.login')}</label><input className="field" defaultValue={String(v.login)} disabled={!!u} required pattern="[A-Za-z0-9_.@-]+" onChange={e => { v.login = e.target.value; }} autoFocus={!u} /></div>
            <div><label className="lbl">{t('adm.name')}</label><input className="field" defaultValue={String(v.name)} required onChange={e => { v.name = e.target.value; }} /></div>
            <div><label className="lbl">{t('adm.role')}</label><select className="field" defaultValue={String(v.role)} onChange={e => { v.role = e.target.value; }}>
              {['operator', 'supervisor', 'admin'].map(r => <option key={r} value={r}>{t(`role.${r}`)}</option>)}</select></div>
            <div><label className="lbl">{u ? t('adm.newPassword') : t('adm.password')}</label><input className="field" type="password" autoComplete="new-password" minLength={4} required={!u} onChange={e => { v.password = e.target.value; }} /></div>
            <div className="full"><label className="lbl">{t('adm.cams')}</label>
              <select className="field" defaultValue={v.all_cameras ? 'all' : 'some'} onChange={e => { v.all_cameras = e.target.value === 'all'; }}>
                <option value="all">{t('adm.allCams')}</option><option value="some">{t('adm.someCams')}</option></select>
              <div className="chips" style={{ marginTop: 10 }}>
                {cams.map(c => <label key={c.id} className="chip" style={{ cursor: 'pointer' }}><input type="checkbox" defaultChecked={(v.camera_ids as string[]).includes(c.id)}
                  onChange={e => { const ids = new Set(v.camera_ids as string[]); e.target.checked ? ids.add(c.id) : ids.delete(c.id); v.camera_ids = [...ids]; }} /> {c.name}</label>)}
              </div></div>
          </div>
        </div>
        <div className="acts"><button type="button" className="btn sm" onClick={() => close(null)}>{t('cancel')}</button><button type="submit" className="btn sm primary">{t('save')}</button></div>
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
  const toggleUser = async (u: AdminUser) => {
    try { await api(`/ui/api/users/${u.id}`, { method: 'PATCH', json: { active: !u.active } }); load(); }
    catch (e) { toast((e as Error).message, 'err'); }
  };
  const addCam = async () => {
    const r = await addCameraDialog(modal, t); if (!r) return;
    try { await api('/ui/api/cameras', { method: 'POST', json: { ...r, fps: 4 } }); toast(t('cam.added', { n: r.name })); refreshCams(); load(); }
    catch (e) { toast((e as Error).message, 'err'); }
  };
  const removeCam = async (c: Camera) => {
    if (!await confirm(t('cam.removeTitle'), <><b>{c.name}</b> {t('cam.removeText', { name: '' })}</>, t('cam.remove'))) return;
    try { await api(`/ui/api/cameras/${c.id}`, { method: 'DELETE' }); toast(t('cam.removed')); refreshCams(); load(); }
    catch (e) { toast((e as Error).message, 'err'); }
  };
  const retention = me?.features.retention_days || 0;

  return (
    <div className="page wide">
      <div className="page-head"><div><h1>{t('adm.title')}</h1><p>{t('adm.lead')}</p></div><div className="acts"><button className="btn primary" onClick={addUser}><Icon id="plus" />{t('adm.addUser')}</button></div></div>
      <div className="stats five">
        <div className="stat"><div className="n">{stats?.jobs.done ?? '—'}</div><div className="l">{t('adm.jobs')}</div></div>
        <div className="stat warn"><div className="n">{stats?.alerts.open ?? '—'}</div><div className="l">{t('adm.alerts')}</div></div>
        <div className="stat ok"><div className="n">{cams.filter(c => c.state?.status === 'online').length}/{cams.length}</div><div className="l">{t('adm.cameras')}</div></div>
        <div className="stat"><div className="n" style={{ fontSize: 22 }}>{me?.analyzer}</div><div className="l">{t('adm.analyzer')} · {me?.version}</div></div>
        <div className="stat"><div className="n" style={{ fontSize: 22 }}>{retention ? t('adm.days', { n: retention }) : t('adm.forever')}</div><div className="l">{t('adm.retention')}</div></div>
      </div>
      <div className="two-col">
        <div className="card">
          <div className="feed-h"><h2>{t('adm.users')}</h2></div>
          <table className="table">
            <thead><tr><th>{t('adm.login')}</th><th>{t('adm.role')}</th><th>{t('adm.cams')}</th><th>{t('adm.lastLogin')}</th><th /></tr></thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id} style={{ opacity: u.active ? 1 : .55 }}>
                  <td><div className="fname"><span className="ic"><Icon id="user" /></span><div><b>{u.name}</b><small>{u.login}{!u.active && <> · {t('adm.inactive')}</>}</small></div></div></td>
                  <td><span className={`pill xs ${u.role === 'admin' ? 'brand' : u.role === 'supervisor' ? 'info' : 'neutral'}`}>{t(`role.${u.role}`)}</span></td>
                  <td className="muted small">{u.camera_ids == null ? t('adm.allCams') : u.camera_ids.map(id => cams.find(c => c.id === id)?.name || id).join(', ') || '—'}</td>
                  <td className="muted small">{u.last_login_at ? fmtDate(u.last_login_at, locale) : t('adm.never')}</td>
                  <td className="c-acts"><div className="row-acts">
                    <button className="btn xs" onClick={() => editUser(u)}>{t('adm.edit')}</button>
                    <button className={`btn xs ${u.active ? 'danger' : 'ok'}`} onClick={() => toggleUser(u)}>{t(u.active ? 'adm.disable' : 'adm.enable')}</button>
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <div className="feed-h"><h2>{t('adm.camsTitle')}</h2><span className="sp" /><button className="btn xs primary" onClick={addCam}><Icon id="plus" />{t('live.addCam')}</button></div>
          <p className="muted small" style={{ padding: '12px 22px 0' }}>{t('adm.camHint')}</p>
          {cams.length ? (
            <table className="table">
              <tbody>
                {cams.map(c => (
                  <tr key={c.id}>
                    <td><div className="fname"><span className="ic"><Icon id="cam" /></span><div><b>{c.name}</b><small>{c.url.replace(/\/\/.*@/, '//***@')}</small></div></div></td>
                    <td><span className={`pill xs ${c.state?.status === 'online' ? 'ok' : 'neutral'}`}>{t(`cam.${c.state?.status || 'stopped'}`)}</span></td>
                    <td className="c-acts"><div className="row-acts"><button className="icon-btn danger" onClick={() => removeCam(c)} title={t('live.removeCam')}><Icon id="trash" /></button></div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="empty"><b>{t('live.noCams')}</b>{t('live.noCamsAdmin')}</div>}
          <div style={{ padding: '14px 22px 20px' }} className="muted small"><b style={{ color: 'var(--fg)' }}>{t('adm.apiKey')}</b> — {t('adm.apiKeyHint')}</div>
        </div>
      </div>
    </div>
  );
}
