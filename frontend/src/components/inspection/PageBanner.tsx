/* Page head of the checks page as a friendly banner: title, lead, the upload action, an illustration. */
import { Upload } from 'lucide-react';
import { useI18n } from '../../i18n';
import { Button } from '../ui/button';
import { DeskIllustration } from './Illustration';

export function PageBanner({ onUpload }: { onUpload: () => void }) {
  const { t } = useI18n();
  return (
    <section className="flex items-center gap-6 overflow-hidden rounded-xl border border-border/60 bg-card px-5 py-5 shadow-sm sm:px-7">
      <div className="min-w-0 flex-1">
        <h1 className="text-[22px] font-semibold tracking-tight text-heading sm:text-2xl">{t('checks.title')}</h1>
        <p className="mt-1.5 max-w-[62ch] text-[14.5px] text-muted-foreground text-pretty">{t('checks.lead')}</p>
        <Button className="mt-4" size="lg" onClick={onUpload}><Upload />{t('checks.upload')}</Button>
      </div>
      <DeskIllustration className="hidden w-[260px] shrink-0 md:block lg:w-[300px]" />
    </section>
  );
}
