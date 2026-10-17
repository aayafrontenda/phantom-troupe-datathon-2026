/* Flat, friendly illustration (Corporate Memphis spirit): a ceiling camera looking down at a cash desk,
   banknotes on the desk, a check badge. Drawn in theme tokens, so it follows light/dark. */
import { cn } from '../../lib/utils';

export function DeskIllustration({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 300 168" className={cn('h-auto w-full', className)} role="img" aria-hidden="true">
      {/* soft ground blob */}
      <path d="M38 120c-14-34 10-72 54-84 30-8 50 6 82-2 40-10 86 4 96 40 9 33-14 62-56 70-36 7-58-6-92 0-40 7-72 6-84-24z" className="fill-muted" />
      {/* memphis confetti */}
      <path d="M22 44q8-10 16 0t16 0" className="fill-none stroke-foreground" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="268" cy="30" r="5" className="fill-primary" />
      <path d="M250 138l10-17 10 17z" className="fill-none stroke-foreground" strokeWidth="2.2" strokeLinejoin="round" />
      <circle cx="40" cy="146" r="3" className="fill-foreground" />
      <path d="M276 92h14M283 85v14" className="stroke-faint" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M16 96a9 9 0 0 1 18 0z" className="fill-border-strong" />

      {/* camera on its arm */}
      <path d="M150 4v14" className="stroke-foreground" strokeWidth="3" strokeLinecap="round" />
      <rect x="128" y="16" width="44" height="22" rx="7" className="fill-foreground" />
      <circle cx="150" cy="38" r="8" className="fill-primary" />
      <circle cx="150" cy="38" r="3" className="fill-card" />
      {/* field of view */}
      <path d="M142 44L86 128h128L158 44z" className="fill-primary" opacity=".09" />
      <path d="M142 44L86 128M158 44l56 84" className="stroke-primary" strokeWidth="1.4" strokeDasharray="3 5" opacity=".55" />

      {/* desk */}
      <rect x="70" y="104" width="160" height="40" rx="10" className="fill-card stroke-border-strong" strokeWidth="1.6" />
      <rect x="70" y="134" width="160" height="10" rx="5" className="fill-border" />
      {/* banknotes */}
      <g transform="rotate(-8 118 112)">
        <rect x="96" y="102" width="46" height="22" rx="4" className="fill-primary-soft stroke-primary" strokeWidth="1.6" />
        <circle cx="119" cy="113" r="5" className="fill-none stroke-primary" strokeWidth="1.6" />
      </g>
      <rect x="104" y="108" width="46" height="22" rx="4" className="fill-card stroke-foreground" strokeWidth="1.6" />
      <circle cx="127" cy="119" r="5" className="fill-none stroke-foreground" strokeWidth="1.6" />
      {/* keyboard / screen edge */}
      <rect x="166" y="110" width="44" height="16" rx="3" className="fill-muted stroke-border-strong" strokeWidth="1.4" />
      <path d="M172 118h32" className="stroke-faint" strokeWidth="2" strokeLinecap="round" strokeDasharray="2 4" />

      {/* check badge */}
      <circle cx="222" cy="74" r="17" className="fill-primary" />
      <path d="M214 74.5l5.5 5.5 10.5-11" className="fill-none stroke-white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      {/* timecode tag */}
      <rect x="54" y="60" width="54" height="20" rx="6" className="fill-card stroke-border-strong" strokeWidth="1.4" />
      <circle cx="65" cy="70" r="3" className="fill-primary" />
      <path d="M73 70h26" className="stroke-foreground" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}
