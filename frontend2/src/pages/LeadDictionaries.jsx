import { useCallback, useEffect, useState } from 'react'
import { Archive, ArchiveRestore, ListChecks, Pencil, Plus } from 'lucide-react'
import api from '../api/axios'
import { Badge, Button, DataTable, EmptyState, Field, Input, Modal, PageHeader, Tabs, apiErrorMessage, plural, useToast } from '../ui'
import { t } from '../i18n'

// Два справочника воронки (TRU-93). usage — во что складывается число
// рядом с названием: заявки для источника, отказы для причины.
const DICTIONARIES = {
  sources: {
    url: 'leads/sources/',
    get tab() { return t('Источники заявок') },
    get hint() { return t('Откуда приходят заявки. Самые частые — сверху, так их быстрее выбрать в новой заявке.') },
    get added() { return t('Источник добавлен') },
    get newTitle() { return t('Новый источник') },
    get editTitle() { return t('Переименовать источник') },
    get placeholder() { return t('Например, реклама у блогера') },
    usage: n => `${n} ${plural(n, ['заявка', 'заявки', 'заявок'])}`,
  },
  reasons: {
    url: 'leads/rejection-reasons/',
    params: { kind: 'new' },
    create: { kind: 'new' },
    get tab() { return t('Причины отказа') },
    get hint() { return t('Обязательны при переводе заявки в «Отказ» — по ним строится отчёт, почему уходят клиенты.') },
    get added() { return t('Причина добавлена') },
    get newTitle() { return t('Новая причина отказа') },
    get editTitle() { return t('Переименовать причину') },
    get placeholder() { return t('Например, переезжают') },
    usage: n => `${n} ${plural(n, ['отказ', 'отказа', 'отказов'])}`,
  },
  // Отказ от продления (TRU-98) — клиент уже свой, свой список причин.
  renewalReasons: {
    url: 'leads/rejection-reasons/',
    params: { kind: 'renewal' },
    create: { kind: 'renewal' },
    get tab() { return t('Отказ от продления') },
    get hint() { return t('Почему клиент не продлил абонемент — отдельно от причин отказа новых заявок, чтобы не путать отчёты.') },
    get added() { return t('Причина добавлена') },
    get newTitle() { return t('Новая причина отказа от продления') },
    get editTitle() { return t('Переименовать причину') },
    get placeholder() { return t('Например, болеет') },
    usage: n => `${n} ${plural(n, ['отказ', 'отказа', 'отказов'])}`,
  },
}

/** Справочники продаж: источники заявок и причины отказа. Удаления нет —
 * архив: в старых заявках значение остаётся, в новых не предлагается. */
export default function LeadDictionaries() {
  const toast = useToast()
  const [kind, setKind] = useState('sources')
  const [data, setData] = useState({ sources: null, reasons: null, renewalReasons: null })
  const [error, setError] = useState(false)
  const [editing, setEditing] = useState(null)
  const dict = DICTIONARIES[kind]

  const load = useCallback(() => {
    const keys = Object.keys(DICTIONARIES)
    Promise.all(keys.map(key => api.get(DICTIONARIES[key].url, { params: DICTIONARIES[key].params })))
      .then(responses => {
        setData(Object.fromEntries(keys.map((key, i) => [key, responses[i].data])))
        setError(false)
      })
      .catch(() => setError(true))
  }, [])
  useEffect(() => { load() }, [load])

  async function toggleArchive(item) {
    try {
      await api.patch(`${dict.url}${item.id}/`, { is_active: !item.is_active })
      toast.success(item.is_active ? t('Убрано в архив') : t('Восстановлено'))
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  const rows = data[kind]
  const activeCount = count => (data[count] || []).filter(item => item.is_active).length

  const columns = [
    { key: 'name', header: t('Название'), primary: true, render: item => <span className="font-semibold text-ink">{t(item.name)}</span> },
    { key: 'usage', header: t('Использовано'), render: item => <span className="text-ink-muted">{dict.usage(item.usage_count)}</span> },
    { key: 'status', header: t('Статус'), mobileAside: true, render: item => (item.is_active ? <Badge tone="success">{t('Активно')}</Badge> : <Badge>{t('В архиве')}</Badge>) },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: item => (
        <span className="inline-flex gap-1" onClick={e => e.stopPropagation()}>
          <Button variant="ghost" size="icon" aria-label={t('Переименовать')} onClick={() => setEditing(item)}><Pencil className="size-4" /></Button>
          <Button variant="ghost" size="icon" aria-label={item.is_active ? t('В архив') : t('Восстановить')} onClick={() => toggleArchive(item)}>
            {item.is_active ? <Archive className="size-4" /> : <ArchiveRestore className="size-4" />}
          </Button>
        </span>
      ),
    },
  ]

  return (
    <div>
      <PageHeader
        title={t('Справочники продаж')}
        description={dict.hint}
        actions={<Button variant="primary" icon={Plus} onClick={() => setEditing('new')}>{t('Добавить')}</Button>}
      />
      <Tabs
        className="mb-4"
        value={kind}
        onChange={setKind}
        tabs={Object.entries(DICTIONARIES).map(([key, d]) => ({ key, label: d.tab, count: data[key] ? activeCount(key) : null }))}
      />
      <DataTable
        columns={columns}
        rows={rows || []}
        loading={!rows && !error}
        error={error}
        onRetry={load}
        onRowClick={item => setEditing(item)}
        empty={<EmptyState icon={ListChecks} title={t('Список пуст')} description={dict.hint} action={<Button variant="primary" icon={Plus} onClick={() => setEditing('new')}>{t('Добавить')}</Button>} />}
      />
      {editing && (
        <DictionaryItemModal
          dict={dict}
          item={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load() }}
        />
      )}
    </div>
  )
}

function DictionaryItemModal({ dict, item, onClose, onSaved }) {
  const toast = useToast()
  const [name, setName] = useState(item?.name || '')
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      if (item) await api.patch(`${dict.url}${item.id}/`, { name })
      else await api.post(dict.url, { name, ...dict.create })
      toast.success(item ? t('Сохранено') : dict.added)
      onSaved()
    } catch (err) {
      const message = err.response?.data?.name?.[0]
      if (message) setError(t(message))
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title={item ? dict.editTitle : dict.newTitle}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="dictionary-form" loading={saving}>{item ? t('Сохранить') : t('Добавить')}</Button>
        </>
      }
    >
      <form id="dictionary-form" onSubmit={submit}>
        <Field label={t('Название')} required error={error}>
          {({ id, invalid }) => (
            <Input id={id} invalid={invalid} value={name} onChange={e => setName(e.target.value)} placeholder={dict.placeholder} minLength={2} maxLength={100} required autoFocus />
          )}
        </Field>
      </form>
    </Modal>
  )
}
