import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Copy, FileText, Lightbulb, RefreshCw, Save, ShieldAlert, Square, Trash2, Video } from 'lucide-react'
import api from '../api/axios'
import { t, useLang } from '../i18n'
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Field, Input, PageHeader, Select, Spinner, Tabs, Textarea, apiErrorMessage, useConfirm, useToast } from '../ui'

const SECTION_TABS = [
  { key: 'posts', label: t('Посты') },
  { key: 'videos', label: t('Сценарии видео') },
  { key: 'history', label: t('История генераций') },
  { key: 'drafts', label: t('Сохранённые варианты') },
]

const STATUS_PENDING = new Set(['queued', 'running'])
const clone = value => JSON.parse(JSON.stringify(value || {}))
const tabForContentType = value => value === 'reel' ? 'videos' : 'posts'

export default function ContentStudio() {
  const interfaceLanguage = useLang()
  const defaultContentLanguage = interfaceLanguage === 'kk' ? 'kk' : 'ru'
  const toast = useToast()
  const confirm = useConfirm()
  const [data, setData] = useState(null)
  const [content, setContent] = useState({})
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(false)
  const [contentType, setContentType] = useState('both')
  const [tab, setTab] = useState('posts')
  const [draftTitle, setDraftTitle] = useState('')
  const [activeDraft, setActiveDraft] = useState(null)
  const [activeHistory, setActiveHistory] = useState(null)
  const [saving, setSaving] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [instructions, setInstructions] = useState('')
  const instructionsTouched = useRef(false)

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setLoading(true)
    try {
      const response = await api.get('ai/content/')
      setData(response.data)
      if (!instructionsTouched.current) setInstructions(response.data.generation?.parameters?.instructions || '')
      setContentType(['full', 'week'].includes(response.data.generation?.parameters?.content_type) ? 'both' : response.data.generation?.parameters?.content_type || 'both')
      if (!activeDraft && !activeHistory) setContent(clone(response.data.content))
      setError(false)
      return response.data
    } catch {
      setError(true)
      return null
    } finally {
      if (!quiet) setLoading(false)
    }
  }, [activeDraft, activeHistory])

  useEffect(() => {
    const timer = window.setTimeout(() => load(), 0)
    return () => window.clearTimeout(timer)
  }, [load])
  useEffect(() => {
    if (!STATUS_PENDING.has(data?.generation?.status)) return undefined
    const timer = window.setInterval(async () => {
      const next = await load({ quiet: true })
      if (next && !STATUS_PENDING.has(next.generation?.status)) {
        setSubmitting(false)
        setContent(clone(next.content))
        setTab(tabForContentType(next.generation?.parameters?.content_type))
      }
    }, 2000)
    return () => window.clearInterval(timer)
  }, [data?.generation?.status, load])

  const generate = async () => {
    setSubmitting(true)
    setActiveDraft(null)
    setActiveHistory(null)
    setDraftTitle('')
    setTab(tabForContentType(contentType))
    try {
      await api.post('ai/content/', { language: defaultContentLanguage, content_type: contentType, instructions: instructions.trim() })
      await load({ quiet: true })
      toast.success(t('Генерация началась'))
    } catch (requestError) {
      setSubmitting(false)
      toast.error(apiErrorMessage(requestError))
    }
  }

  const cancelGeneration = async () => {
    const generationId = data?.generation?.id
    if (!generationId) return
    setCancelling(true)
    try {
      await api.post(`ai/content/${generationId}/cancel/`)
      setSubmitting(false)
      await load({ quiet: true })
      toast.success(t('Генерация отменена'))
    } catch (requestError) {
      toast.error(apiErrorMessage(requestError))
    } finally {
      setCancelling(false)
    }
  }

  const saveDraft = async () => {
    if (draftTitle.trim().length < 3) {
      toast.error(t('Введите название варианта — минимум 3 символа'))
      return
    }
    setSaving(true)
    try {
      const payload = { title: draftTitle.trim(), language: content.language || defaultContentLanguage, payload: content }
      let response
      if (activeDraft) response = await api.patch(`ai/content/drafts/${activeDraft}/`, payload)
      else response = await api.post('ai/content/drafts/', { ...payload, generation: activeHistory || data?.generation?.id })
      setActiveDraft(response.data.id)
      setActiveHistory(null)
      setDraftTitle(response.data.title)
      await load({ quiet: true })
      toast.success(t('Вариант сохранён'))
    } catch (requestError) {
      toast.error(apiErrorMessage(requestError))
    } finally {
      setSaving(false)
    }
  }

  const openDraft = draft => {
    setActiveDraft(draft.id)
    setActiveHistory(null)
    setDraftTitle(draft.title)
    setContent(clone(draft.payload))
    setTab('posts')
  }

  const openHistory = generation => {
    setActiveDraft(null)
    setActiveHistory(generation.id)
    setDraftTitle('')
    setContent(clone(generation.content))
    setTab(tabForContentType(generation.content_type))
  }

  const deleteDraft = async draft => {
    const accepted = await confirm({ title: t('Удалить сохранённый вариант?'), confirmText: t('Удалить'), danger: true })
    if (!accepted) return
    try {
      await api.delete(`ai/content/drafts/${draft.id}/`)
      if (activeDraft === draft.id) {
        setActiveDraft(null)
        setDraftTitle('')
        setContent(clone(data?.content))
      }
      await load({ quiet: true })
      toast.success(t('Вариант удалён'))
    } catch (requestError) {
      toast.error(apiErrorMessage(requestError))
    }
  }

  const updateRow = (section, index, key, value) => setContent(current => ({
    ...current,
    [section]: current[section].map((row, rowIndex) => rowIndex === index ? { ...row, [key]: value } : row),
  }))

  const copyText = async text => {
    await navigator.clipboard.writeText(text)
    toast.success(t('Скопировано'))
  }

  const counts = useMemo(() => Object.fromEntries(SECTION_TABS.map(item => {
    if (item.key === 'drafts') return [item.key, data?.drafts?.length || 0]
    if (item.key === 'history') return [item.key, data?.history?.length || 0]
    return [item.key, content[item.key]?.length || 0]
  })), [content, data?.drafts, data?.history])
  const generationStatus = data?.generation?.status
  const generating = submitting || STATUS_PENDING.has(generationStatus)
  const degraded = generationStatus && !['queued', 'running', 'succeeded'].includes(generationStatus)

  return (
    <>
      <PageHeader
        title={t('Контент-помощник')}
        description={t('Готовые посты и сценарии Reels на основе реальных данных CRM')}
        actions={(
          <div className="flex w-full flex-wrap gap-2 sm:w-auto">
            <Select value={contentType} onChange={event => setContentType(event.target.value)} className="min-w-40 flex-1 sm:flex-none" aria-label={t('Формат результата')}>
              <option value="post">{t('Посты')}</option>
              <option value="reel">{t('Reels')}</option>
              <option value="both">{t('Посты и Reels')}</option>
            </Select>
            {generating ? (
              <Button icon={Square} loading={cancelling} onClick={cancelGeneration}>{t('Отменить генерацию')}</Button>
            ) : (
              <Button variant="primary" icon={RefreshCw} onClick={generate}>{t('Сгенерировать')}</Button>
            )}
          </div>
        )}
      />

      <Card className="mb-4">
        <Field label={t('Пожелания к генерации')}>
          <Textarea
            rows={3}
            maxLength={1000}
            value={instructions}
            placeholder={t('Например: спокойный тон для родителей подростков, больше идей для коротких видео, без акцента на соревнованиях')}
            onChange={event => {
              instructionsTouched.current = true
              setInstructions(event.target.value)
            }}
          />
        </Field>
        <div className="mt-2 flex justify-end text-xs text-ink-subtle">
          <span>{instructions.length}/1000</span>
        </div>
      </Card>

      {loading ? <Card><Spinner /></Card> : error ? <Card><ErrorState onRetry={load} /></Card> : (
        <div className="space-y-4">
          {degraded && (
            <Card className="flex items-start gap-3 border-warning-50 bg-warning-50/40">
              <ShieldAlert className="mt-0.5 size-5 shrink-0 text-warning-600" />
              <div><p className="font-semibold text-ink">{t('Контент пока не сгенерирован')}</p><p className="mt-1 text-sm text-ink-muted">{generationStatus === 'schema_error' ? t('ИИ добавил неподтверждённые условия. Ответ отклонён — попробуйте сгенерировать ещё раз.') : data.generation.error || t('Попробуйте ещё раз позже.')}</p></div>
            </Card>
          )}

          {generationStatus === 'succeeded' || activeDraft || activeHistory ? (
            <>
              <Card className="flex flex-col gap-3 sm:flex-row sm:items-end">
                <Field label={t('Название варианта')} className="min-w-0 flex-1">
                  {({ id }) => <Input id={id} value={draftTitle} maxLength={120} placeholder={t('Например, контент на следующую неделю')} onChange={event => setDraftTitle(event.target.value)} />}
                </Field>
                <Button icon={Save} loading={saving} onClick={saveDraft}>{activeDraft ? t('Сохранить изменения') : t('Сохранить вариант')}</Button>
              </Card>
              <Card padded={false}>
                <Tabs className="px-4 pt-3 sm:px-5" tabs={SECTION_TABS.map(item => ({ ...item, count: counts[item.key] }))} value={tab} onChange={setTab} />
                <div className="p-4 sm:p-5">
                  {tab === 'posts' && <Posts rows={content.posts || []} update={updateRow} copy={copyText} />}
                  {tab === 'videos' && <Videos rows={content.videos || []} update={updateRow} copy={copyText} />}
                  {tab === 'history' && <GenerationHistory rows={data.history || []} open={openHistory} />}
                  {tab === 'drafts' && <Drafts rows={data.drafts || []} open={openDraft} remove={deleteDraft} />}
                </div>
              </Card>
            </>
          ) : !generating && !degraded && (
            <Card><EmptyState icon={Lightbulb} title={t('Создайте первый материал')} description={t('Помощник возьмёт только обезличенные показатели CRM и подставит реальные данные групп кодом.')} action={<Button variant="primary" onClick={generate}>{t('Сгенерировать')}</Button>} /></Card>
          )}
          {generating && <Card><Spinner label={t('Готовим идеи и тексты в фоне…')} /></Card>}
        </div>
      )}
    </>
  )
}

function Posts({ rows, update, copy }) {
  if (!rows.length) return <EmptyState icon={FileText} title={t('Готовых постов пока нет')} />
  return <div className="grid gap-4 xl:grid-cols-2">{rows.map((row, index) => (
    <Card key={`${row.candidate_key}-${index}`} className="bg-surface-muted/30">
      <CardHeader title={row.group} description={t('Реальные расписание и свободные места уже подставлены')} actions={<Button size="sm" icon={Copy} onClick={() => copy(row.text)}>{t('Копировать')}</Button>} />
      <Field label={t('Готовый текст')}><Textarea rows={12} value={row.text} onChange={event => update('posts', index, 'text', event.target.value)} /></Field>
    </Card>
  ))}</div>
}

function Videos({ rows, update, copy }) {
  if (!rows.length) return <EmptyState icon={Video} title={t('Сценариев пока нет')} />
  return <div className="space-y-4">{rows.map((row, index) => {
    const script = `${row.title}\n\n${row.shots.map((shot, shotIndex) => `${shotIndex + 1}. ${shot}`).join('\n')}\n\n${row.caption}`
    return <Card key={`${row.candidate_key}-${index}`} className="bg-surface-muted/30">
      <CardHeader title={row.group} actions={<Button size="sm" icon={Copy} onClick={() => copy(script)}>{t('Копировать сценарий')}</Button>} />
      <Field label={t('Название')}><Input value={row.title} onChange={event => update('videos', index, 'title', event.target.value)} /></Field>
      <div className="mt-4 grid gap-3 md:grid-cols-2">{row.shots.map((shot, shotIndex) => <Field key={shotIndex} label={`${t('Кадр')} ${shotIndex + 1}`}><Textarea value={shot} onChange={event => update('videos', index, 'shots', row.shots.map((value, valueIndex) => valueIndex === shotIndex ? event.target.value : value))} /></Field>)}</div>
      <Field className="mt-4" label={t('Подпись к видео')}><Textarea value={row.caption} onChange={event => update('videos', index, 'caption', event.target.value)} /></Field>
      <div className="mt-4 flex items-start gap-2 rounded-md bg-warning-50 px-3 py-2 text-xs text-warning-600"><ShieldAlert className="mt-0.5 size-4 shrink-0" /><span>{t('Перед съёмкой убедитесь, что центр получил согласие родителей на публикацию детей.')}</span></div>
    </Card>
  })}</div>
}

function Drafts({ rows, open, remove }) {
  if (!rows.length) return <EmptyState icon={Save} title={t('Сохранённых вариантов пока нет')} description={t('Отредактируйте материалы и сохраните вариант, чтобы вернуться к нему позже.')} />
  return <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{rows.map(draft => {
    const payload = draft.payload || {}
    const preview = payload.posts?.[0]?.text || payload.posts?.[0]?.hook || payload.videos?.[0]?.title || ''
    const sections = [
      [t('Посты'), payload.posts?.length || 0],
      [t('Сценарии видео'), payload.videos?.length || 0],
    ]
    return (
      <Card key={draft.id} className="flex min-h-56 flex-col bg-surface-muted/30">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0"><p className="truncate font-semibold text-ink">{draft.title}</p><p className="mt-1 text-xs text-ink-subtle">{draft.language.toUpperCase()}</p></div>
          <Button size="icon" variant="danger-ghost" icon={Trash2} aria-label={t('Удалить')} onClick={() => remove(draft)} />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">{sections.map(([label, count]) => <Badge key={label} tone="neutral">{label}: {count}</Badge>)}</div>
        {preview && <p className="mt-4 line-clamp-3 text-sm leading-6 text-ink-muted">{preview}</p>}
        <div className="mt-auto pt-4"><Button className="w-full" onClick={() => open(draft)}>{t('Открыть вариант')}</Button></div>
      </Card>
    )
  })}</div>
}

function GenerationHistory({ rows, open }) {
  if (!rows.length) return <EmptyState icon={RefreshCw} title={t('История генераций пока пуста')} description={t('Каждый успешный результат появится здесь автоматически, даже если его не сохранять.')} />
  return <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{rows.map(generation => {
    const payload = generation.content || {}
    const preview = payload.posts?.[0]?.text || payload.posts?.[0]?.hook || payload.videos?.[0]?.title || ''
    const format = generation.content_type === 'post' ? t('Посты') : generation.content_type === 'reel' ? t('Reels') : t('Посты и Reels')
    return (
      <Card key={generation.id} className="flex min-h-52 flex-col bg-surface-muted/30">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div><p className="font-semibold text-ink">{format}</p><p className="mt-1 text-xs text-ink-subtle">{new Date(generation.created_at).toLocaleString()}</p></div>
          <Badge tone="neutral">{generation.language.toUpperCase()}</Badge>
        </div>
        {generation.instructions && <p className="mt-3 line-clamp-2 text-sm text-ink-muted">{generation.instructions}</p>}
        {preview && <p className="mt-3 line-clamp-3 text-sm leading-6 text-ink-muted">{preview}</p>}
        <div className="mt-auto pt-4"><Button className="w-full" onClick={() => open(generation)}>{t('Открыть результат')}</Button></div>
      </Card>
    )
  })}</div>
}
