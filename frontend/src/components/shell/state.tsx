import { BookOpenCheck, ChartColumn, Cctv, ListVideo, Settings, UserCheck, type LucideIcon } from 'lucide-react';

export type Need = 'operator' | 'supervisor' | 'admin';
export interface NavItem { to: string; label: string; icon: LucideIcon; need?: Need; match: string[]; badge?: 'open' }
export const NAV: NavItem[] = [
  { to: '/checks', label: 'nav.checks', icon: ListVideo, match: ['checks'] },
  { to: '/live', label: 'nav.live', icon: Cctv, match: ['live', 'findings'], badge: 'open' },
  { to: '/review', label: 'nav.review', icon: UserCheck, need: 'supervisor', match: ['review'] },
  { to: '/quality', label: 'nav.quality', icon: ChartColumn, need: 'supervisor', match: ['quality'] },
  { to: '/rules', label: 'nav.rules', icon: BookOpenCheck, match: ['rules'] },
  { to: '/admin', label: 'nav.admin', icon: Settings, need: 'admin', match: ['admin'] },
];

export const section = (pathname: string) => pathname.split('/')[1] || '';
