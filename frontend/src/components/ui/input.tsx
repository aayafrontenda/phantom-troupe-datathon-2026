import { Eye, EyeOff } from 'lucide-react';
import * as React from 'react';
import { cn } from '@/lib/utils';

export const fieldClass =
  'w-full rounded-lg border border-input bg-card text-sm text-foreground transition-[border-color,box-shadow] duration-150 placeholder:text-faint hover:border-border-strong focus:border-primary focus:outline-none focus:ring-3 focus:ring-primary-soft disabled:cursor-not-allowed disabled:opacity-60';

const Input = React.forwardRef<HTMLInputElement, Omit<React.InputHTMLAttributes<HTMLInputElement>, 'size'> & { size?: 'default' | 'sm' }>(
  ({ className, size = 'default', type = 'text', ...props }, ref) => (
    <input ref={ref} type={type} data-slot="input"
      className={cn(fieldClass, size === 'sm' ? 'h-8 px-2.5 text-[13px]' : 'h-9 px-3', className)} {...props} />
  ),
);
Input.displayName = 'Input';

type PasswordInputProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, 'size' | 'type'> & {
  size?: 'default' | 'sm';
  showLabel: string;
  hideLabel: string;
};

const PasswordInput = React.forwardRef<HTMLInputElement, PasswordInputProps>(
  ({ className, showLabel, hideLabel, size = 'default', ...props }, ref) => {
    const [visible, setVisible] = React.useState(false);
    return (
      <div className="relative">
        <Input ref={ref} size={size} type={visible ? 'text' : 'password'} className={cn('pr-10', className)} {...props} />
        <button type="button" onClick={() => setVisible(v => !v)} onMouseDown={e => e.preventDefault()}
          aria-label={visible ? hideLabel : showLabel} aria-pressed={visible} title={visible ? hideLabel : showLabel}
          className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-lg text-faint transition-colors hover:text-foreground focus-visible:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40">
          {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </button>
      </div>
    );
  },
);
PasswordInput.displayName = 'PasswordInput';

const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...props }, ref) => (
  <textarea ref={ref} data-slot="textarea" className={cn(fieldClass, 'min-h-24 resize-y px-3 py-2.5 leading-relaxed', className)} {...props} />
));
Textarea.displayName = 'Textarea';

const Label = ({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) => (
  <label data-slot="label" className={cn('mb-1.5 block text-[13px] font-semibold text-muted-foreground', className)} {...props} />
);

export { Input, Label, PasswordInput, Textarea };
