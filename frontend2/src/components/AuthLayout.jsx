import { t } from '../i18n'
import LanguageSwitcher from './shell/LanguageSwitcher'
const FEATURES = [
  t('База детей и родителей без дублей'),
  t('Расписание, группы и посещаемость'),
  t('Абонементы, оплаты и задолженности'),
]

/** Макет страниц входа и регистрации: слева — бренд, справа — форма. */
export default function AuthLayout({ children }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <aside className="relative hidden overflow-hidden bg-gradient-to-br from-brand-500 via-brand-400 to-brand-200 p-14 text-white lg:flex lg:flex-col lg:justify-between">
        <svg className="pointer-events-none absolute inset-0 size-full opacity-15" viewBox="0 0 720 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
          <path d="M-50,220 C150,20 350,420 550,170 C700,0 780,160 820,100" fill="none" stroke="#fff" strokeWidth="2" />
          <path d="M-50,470 C150,270 350,670 550,420" fill="none" stroke="#fff" strokeWidth="1.5" />
          <circle cx="620" cy="120" r="210" fill="none" stroke="#fff" />
          <circle cx="90" cy="780" r="160" fill="none" stroke="#fff" />
        </svg>
        <div className="relative flex items-center gap-2.5">
          <span className="flex size-10 items-center justify-center rounded-lg bg-white/20 backdrop-blur">
            <svg viewBox="0 0 24 24" className="size-5" fill="currentColor" aria-hidden="true">
              <path d="M12 2 2 7l10 5 10-5-10-5Zm-10 15 10 5 10-5M2 12l10 5 10-5" />
            </svg>
          </span>
          <span className="text-lg font-bold">KidsCRM</span>
        </div>
        <div className="relative max-w-md">
          <h1 className="text-4xl font-bold leading-tight tracking-tight">{t('Весь центр —')}<br />{t('в одном месте')}</h1>
          <p className="mt-4 text-base text-white/85">{t('Замените Excel и переписки в WhatsApp: дети, расписание и деньги под контролем.')}</p>
          <ul className="mt-8 space-y-3">
            {FEATURES.map(f => (
              <li key={f} className="flex items-center gap-3 text-[15px] font-medium">
                <span className="size-2 rounded-full bg-white" />
                {f}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-white/70">© 2026 KidsCRM</p>
      </aside>

      <main className="relative flex items-center justify-center px-5 py-12">
        <div className="absolute right-5 top-5"><LanguageSwitcher /></div>
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <span className="flex size-9 items-center justify-center rounded-md bg-gradient-to-br from-brand-400 to-brand-600 text-white">
              <svg viewBox="0 0 24 24" className="size-[18px]" fill="currentColor" aria-hidden="true">
                <path d="M12 2 2 7l10 5 10-5-10-5Zm-10 15 10 5 10-5M2 12l10 5 10-5" />
              </svg>
            </span>
            <span className="text-[17px] font-bold">KidsCRM</span>
          </div>
          {children}
        </div>
      </main>
    </div>
  )
}
