import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowRight, Check, CircleDashed, FileSpreadsheet, Plus, SkipForward, Sparkles } from 'lucide-react'
import api from '../api/axios'
import BranchModal from '../components/BranchModal'
import DirectionModal from '../components/DirectionModal'
import GroupModal from '../components/GroupModal'
import OrganizationForm from '../components/OrganizationForm'
import { useSession } from '../session/SessionContext'
import { Badge, Button, Card, CardHeader, ErrorState, PageHeader, Spinner, apiErrorMessage, cn, useToast } from '../ui'
import { t } from '../i18n'

// Мастер настройки центра (TRU-86). Сам ничего не создаёт — каждый шаг
// открывает те же формы, что обычные экраны (филиал, направление, группа,
// импорт), а шаг засчитывается по данным (backend: tenants/onboarding.py).
// Поэтому филиал, заведённый в «Настройках» мимо мастера, тоже засчитан.

const STEP_INFO = {
  organization: { description: t('Название, часовой пояс и когда подсвечивать продления и долги. Можно оставить как есть.') },
  branch: { description: t('Где проходят занятия. У филиала — адрес, часы работы и залы.'), list: 'branches/', add: t('Добавить филиал') },
  directions: { description: t('Чему учите: балет, растяжка, хореография. По направлениям строятся группы и абонементы.'), list: 'directions/', add: t('Добавить направление') },
  subscription_types: { description: t('Какие абонементы продаёте: на 8 занятий, безлимит и т.п.') },
  groups: { description: t('Группы с преподавателем и вместимостью — в них записываются дети.'), list: 'groups/', add: t('Создать группу') },
  import: { description: t('Загрузите базу детей и родителей из Excel — дубли найдём и спросим, что с ними делать.') },
}

export default function Onboarding() {
  const [params, setParams] = useSearchParams()
  const [state, setState] = useState(null)
  const [error, setError] = useState(false)

  const load = useCallback(() => api.get('onboarding/')
    .then(r => { setState(r.data); setError(false); return r.data })
    .catch(() => setError(true)), [])
  useEffect(() => { load() }, [load])

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (!state) return <Spinner />

  const keys = state.steps.map(s => s.key)
  const requested = params.get('step')
  const active = keys.includes(requested) || requested === 'done' ? requested : (state.current || 'done')
  const goTo = key => setParams({ step: key })
  const nextAfter = key => {
    const index = keys.indexOf(key)
    return keys.slice(index + 1).find(k => state.steps.find(s => s.key === k).status === 'todo') || 'done'
  }

  return (
    <div>
      <PageHeader title={t('Настройка центра')} description={t('Готово {done} из {total}. Любой шаг можно пропустить и вернуться позже.', { done: state.done, total: state.total })} />
      <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
        <StepList steps={state.steps} active={active} onSelect={goTo} />
        <div className="min-w-0">
          {active === 'done' ? (
            <DoneStep state={state} onSelect={goTo} />
          ) : (
            <StepPanel
              key={active}
              step={state.steps.find(s => s.key === active)}
              reload={load}
              onNext={() => goTo(nextAfter(active))}
            />
          )}
        </div>
      </div>
    </div>
  )
}

function StepList({ steps, active, onSelect }) {
  const done = steps.filter(s => s.status === 'done').length
  return (
    <div className="min-w-0">
      <div className="mb-4 h-1.5 overflow-hidden rounded-full bg-surface-muted lg:hidden">
        <div className="h-full rounded-full bg-brand-600" style={{ width: `${(done / steps.length) * 100}%` }} />
      </div>
      <ol className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 lg:mx-0 lg:flex-col lg:overflow-visible lg:px-0">
        {steps.map((step, index) => (
          <li key={step.key} className="shrink-0">
            <button
              type="button"
              onClick={() => onSelect(step.key)}
              aria-current={active === step.key ? 'step' : undefined}
              className={cn(
                'flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors',
                active === step.key ? 'bg-surface font-semibold text-ink shadow-card' : 'text-ink-muted hover:bg-surface/60 hover:text-ink',
              )}
            >
              <span className={cn(
                'flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-bold',
                step.status === 'done' ? 'bg-success-50 text-success-600' : step.status === 'skipped' ? 'bg-warning-50 text-warning-600' : active === step.key ? 'bg-brand-600 text-white' : 'bg-surface-muted text-ink-subtle',
              )}>
                {step.status === 'done' ? <Check className="size-3.5" /> : step.status === 'skipped' ? <SkipForward className="size-3" /> : index + 1}
              </span>
              <span className="whitespace-nowrap">{t(step.title)}</span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  )
}

function StepPanel({ step, reload, onNext }) {
  const toast = useToast()
  const info = STEP_INFO[step.key]
  const [skipping, setSkipping] = useState(false)

  async function skip() {
    setSkipping(true)
    try {
      await api.post(`onboarding/${step.key}/skip/`)
      await reload()
      onNext()
    } catch (err) {
      toast.error(apiErrorMessage(err))
      setSkipping(false)
    }
  }

  const skipButton = step.status !== 'done' && (
    <Button variant="ghost" icon={SkipForward} loading={skipping} onClick={skip}>{t('Пропустить, вернусь позже')}</Button>
  )
  const nextButton = <Button variant="primary" icon={ArrowRight} onClick={onNext}>{t('Дальше')}</Button>

  if (step.key === 'organization') {
    return (
      <div className="max-w-3xl space-y-4">
        <Card><CardHeader className="mb-0" title={t('Организация')} description={info.description} /></Card>
        <OrganizationForm
          submitLabel={t('Сохранить и дальше')}
          onSaved={async () => { await reload(); onNext() }}
          secondaryAction={step.status === 'done' ? nextButton : <ConfirmOrganization reload={reload} onNext={onNext} />}
        />
      </div>
    )
  }

  return (
    <Card>
      <CardHeader
        title={t(step.title)}
        description={info.description}
        actions={step.status === 'done' ? <Badge tone="success" dot>{t('Готово')}</Badge> : step.status === 'skipped' ? <Badge tone="warning">{t('Пропущено')}</Badge> : null}
      />
      {info.list && <ItemsStep step={step} info={info} reload={reload} />}
      {step.key === 'subscription_types' && (
        <div className="flex items-start gap-3 rounded-lg bg-surface-muted p-4 text-sm text-ink-muted">
          <Sparkles className="mt-0.5 size-4 shrink-0 text-brand-600" />
          {t('Экран типов абонементов скоро появится (TRU-74). Пропустите шаг — вернётесь к нему, когда он будет готов.')}
        </div>
      )}
      {step.key === 'import' && (
        <div className="flex flex-col items-start gap-3 rounded-lg bg-surface-muted p-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="flex items-center gap-2 text-sm text-ink-muted"><FileSpreadsheet className="size-4 text-brand-600" /> {t('Импорт откроется на отдельной странице, потом вернитесь сюда.')}</p>
          <Button to="/children/import" icon={ArrowRight}>{t('Открыть импорт')}</Button>
        </div>
      )}
      <div className="mt-6 flex flex-col-reverse gap-2 border-t border-line pt-4 sm:flex-row sm:justify-between">
        <div>{skipButton}</div>
        {step.status === 'done' ? nextButton : <p className="self-center text-[13px] text-ink-subtle">{t('Шаг засчитается, когда появится первая запись.')}</p>}
      </div>
    </Card>
  )
}

function ConfirmOrganization({ reload, onNext }) {
  const toast = useToast()
  const [loading, setLoading] = useState(false)
  async function confirm() {
    setLoading(true)
    try {
      await api.post('onboarding/organization/confirm/')
      await reload()
      onNext()
    } catch (err) {
      toast.error(apiErrorMessage(err))
      setLoading(false)
    }
  }
  return <Button loading={loading} onClick={confirm}>{t('Всё верно, дальше')}</Button>
}

/** Список уже заведённого + та же модалка, что на обычном экране. */
function ItemsStep({ step, info, reload }) {
  const [items, setItems] = useState(null)
  const [branches, setBranches] = useState([])
  const [adding, setAdding] = useState(false)

  const load = useCallback(() => {
    api.get(info.list).then(r => setItems(r.data.results || r.data)).catch(() => setItems([]))
    if (step.key === 'directions') api.get('branches/').then(r => setBranches(r.data.results || r.data)).catch(() => {})
  }, [info.list, step.key])
  useEffect(() => { load() }, [load])

  const saved = () => { setAdding(false); load(); reload() }

  return (
    <div>
      {!items && <Spinner className="py-4" />}
      {items && items.length > 0 && (
        <ul className="mb-3 flex flex-wrap gap-2">
          {items.map(item => (
            <li key={item.id} className="flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1.5 text-sm text-ink">
              {item.color && <span className="size-2.5 rounded-full" style={{ backgroundColor: item.color }} />}
              {item.name}
            </li>
          ))}
        </ul>
      )}
      {items && items.length === 0 && (
        <p className="mb-3 flex items-center gap-2 text-sm text-ink-subtle"><CircleDashed className="size-4" /> {t('Пока ничего нет.')}</p>
      )}
      <Button icon={Plus} onClick={() => setAdding(true)}>{info.add}</Button>

      {adding && step.key === 'branch' && <BranchModal onClose={() => setAdding(false)} onSaved={saved} />}
      {adding && step.key === 'directions' && <DirectionModal branches={branches} onClose={() => setAdding(false)} onSaved={saved} />}
      {adding && step.key === 'groups' && <GroupModal onClose={() => setAdding(false)} onSaved={saved} />}
    </div>
  )
}

function DoneStep({ state, onSelect }) {
  const navigate = useNavigate()
  const toast = useToast()
  const { reload } = useSession()
  const [finishing, setFinishing] = useState(false)
  const skipped = state.steps.filter(s => s.status !== 'done')

  async function finish() {
    setFinishing(true)
    try {
      await api.post('onboarding/finish/')
      await reload()
      toast.success(t('Настройка завершена'))
      navigate('/dashboard')
    } catch (err) {
      toast.error(apiErrorMessage(err))
      setFinishing(false)
    }
  }

  return (
    <Card className="text-center">
      <span className="mx-auto mb-4 flex size-14 items-center justify-center rounded-full bg-success-50 text-success-600"><Check className="size-7" /></span>
      <h2 className="text-xl font-bold text-ink">{skipped.length ? t('Основное готово') : t('Центр настроен')}</h2>
      <p className="mx-auto mt-1 max-w-md text-sm text-ink-muted">
        {skipped.length
          ? t('Пропущенные шаги можно пройти сейчас или позже — они останутся на главной, пока вы не завершите настройку.')
          : t('Всё на месте: филиалы, направления и группы. Можно работать.')}
      </p>
      {skipped.length > 0 && (
        <ul className="mx-auto mt-5 max-w-sm divide-y divide-line rounded-lg border border-line text-left">
          {skipped.map(step => (
            <li key={step.key} className="flex items-center justify-between px-4 py-2.5 text-sm">
              <span className="text-ink">{t(step.title)}</span>
              <button type="button" onClick={() => onSelect(step.key)} className="font-semibold text-brand-700 hover:underline">{t('Пройти')}</button>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        <Button variant="primary" loading={finishing} onClick={finish}>{t('Завершить настройку')}</Button>
        <Button to="/dashboard" variant="ghost">{t('На главную')}</Button>
      </div>
      <p className="mt-4 text-xs text-ink-subtle">{t('Изменить всё это можно в любой момент в')} <Link to="/branches" className="underline">{t('Настройках')}</Link>.</p>
    </Card>
  )
}
