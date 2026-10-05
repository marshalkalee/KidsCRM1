import { useCallback, useEffect, useState } from 'react'
import { Archive, ArchiveRestore, Globe, MessageCircle, Pencil, Plus } from 'lucide-react'
import api from '../../api/axios'
import { Badge, Button, Card, CardHeader, Dropdown, EmptyState, ErrorState, Field, Input, Modal, Select, Skeleton, apiErrorMessage, cn, plural, useToast } from '../../ui'
import { t } from '../../i18n'

/**
 * Публикации и кампании (TRU-165). Instagram не сообщает, после какого
 * ролика написал родитель, — поэтому у каждой публикации свой код (K12) и
 * готовые ссылки: WhatsApp филиала с кодом в тексте и сайт с меткой.
 * Ссылку вставляют под ролик — заявка с кодом получит публикацию сама.
 */
export default function Campaigns() {
  const toast = useToast()
  const [rows, setRows] = useState(null)
  const [sources, setSources] = useState([])
  const [error, setError] = useState(false)
  const [editing, setEditing] = useState(null)

  const fetchRows = useCallback(() => api.get('leads/campaigns/').then(res => setRows(res.data)).catch(() => setError(true)), [])
  useEffect(() => {
    fetchRows()
    api.get('leads/sources/', { params: { active: 1 } }).then(res => setSources(res.data)).catch(() => {})
  }, [fetchRows])
  const retry = () => { setError(false); fetchRows() }

  async function copy(text, done) {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(done)
    } catch {
      toast.error(t('Не удалось скопировать — выделите и скопируйте вручную'))
    }
  }

  async function toggleArchive(row) {
    try {
      await api.patch(`leads/campaigns/${row.id}/`, { is_active: !row.is_active })
      toast.success(row.is_active ? t('Убрано в архив') : t('Восстановлено'))
      fetchRows()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  if (error) return <Card><ErrorState onRetry={retry} /></Card>
  if (!rows) return <Skeleton className="h-64" />

  return (
    <Card>
      <CardHeader
        title={t('Публикации и кампании')}
        description={t('У каждой публикации свой код. Вставьте ссылку под ролик — заявка, пришедшая по ней, сама запишет, с какого ролика пришла. В отчёте по источникам видно, какие публикации приводят клиентов.')}
        actions={<Button variant="primary" size="sm" icon={Plus} onClick={() => setEditing('new')} disabled={!sources.length}>{t('Добавить публикацию')}</Button>}
      />
      {rows.length === 0 ? (
        <EmptyState icon={MessageCircle} title={t('Публикаций пока нет')} description={t('Добавьте ролик или пост — получите ссылку с кодом для подписи.')} />
      ) : (
        <ul className="divide-y divide-line">
          {rows.map(row => (
            <li key={row.id} className={cn('flex flex-wrap items-center gap-x-3 gap-y-2 py-3', !row.is_active && 'opacity-60')}>
              <div className="min-w-[12rem] flex-1">
                <p className="text-sm font-semibold text-ink">{row.name}</p>
                <p className="text-xs text-ink-muted">
                  {t(row.source_name)} · <span className="font-semibold text-ink">{row.code}</span> · {row.usage_count} {plural(row.usage_count, ['заявка', 'заявки', 'заявок'])}
                </p>
              </div>
              {!row.is_active && <Badge>{t('В архиве')}</Badge>}
              <span className="ml-auto inline-flex flex-wrap items-center gap-1.5">
                {row.whatsapp_links.length === 1 && (
                  <Button size="sm" icon={MessageCircle} onClick={() => copy(row.whatsapp_links[0].url, t('Ссылка WhatsApp скопирована'))}>{t('WhatsApp')}</Button>
                )}
                {row.whatsapp_links.length > 1 && (
                  <Dropdown
                    size="sm"
                    value=""
                    placeholder={<span className="inline-flex items-center gap-1.5"><MessageCircle className="size-4" />WhatsApp</span>}
                    ariaLabel={t('Ссылка WhatsApp: филиал')}
                    options={row.whatsapp_links.map(l => ({ value: l.url, label: l.branch }))}
                    onChange={url => copy(url, t('Ссылка WhatsApp скопирована'))}
                    className="!h-8 !w-auto"
                  />
                )}
                {row.site_link && (
                  <Button size="sm" icon={Globe} onClick={() => copy(row.site_link, t('Ссылка на сайт скопирована'))}>{t('Сайт')}</Button>
                )}
                <Button variant="ghost" size="icon" aria-label={t('Переименовать')} onClick={() => setEditing(row)}><Pencil className="size-4" /></Button>
                <Button variant="ghost" size="icon" aria-label={row.is_active ? t('В архив') : t('Восстановить')} onClick={() => toggleArchive(row)}>
                  {row.is_active ? <Archive className="size-4" /> : <ArchiveRestore className="size-4" />}
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {rows.some(r => r.whatsapp_links.length === 0) && (
        <p className="mt-3 text-[13px] text-ink-muted">{t('Ссылки WhatsApp не появились — укажите телефон филиала в «Настройки → Филиалы».')}</p>
      )}
      {editing && (
        <CampaignModal
          campaign={editing === 'new' ? null : editing}
          sources={sources}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); fetchRows() }}
        />
      )}
    </Card>
  )
}

function CampaignModal({ campaign, sources, onClose, onSaved }) {
  const toast = useToast()
  const [name, setName] = useState(campaign?.name || '')
  const [source, setSource] = useState(campaign?.source || String(sources.find(s => s.name === 'Instagram')?.id || sources[0]?.id || ''))
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    try {
      if (campaign) await api.patch(`leads/campaigns/${campaign.id}/`, { name })
      else await api.post('leads/campaigns/', { name, source })
      toast.success(campaign ? t('Сохранено') : t('Публикация добавлена'))
      onSaved()
    } catch (err) {
      const data = err.response?.data || {}
      if (data.name || data.source) setErrors({ name: data.name?.[0], source: data.source?.[0] })
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
      title={campaign ? t('Переименовать публикацию') : t('Новая публикация')}
      description={campaign ? t('Код {code} не меняется — он уже в ссылках под роликом.', { code: campaign.code }) : null}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="campaign-form" loading={saving}>{campaign ? t('Сохранить') : t('Добавить')}</Button>
        </>
      }
    >
      <form id="campaign-form" onSubmit={submit} className="space-y-4">
        <Field label={t('Название')} required error={errors.name}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={name} onChange={e => setName(e.target.value)} placeholder={t('Например, Reel про пробное, сентябрь')} maxLength={100} required autoFocus />}
        </Field>
        {!campaign && (
          <Field label={t('Источник')} error={errors.source}>
            {({ id, invalid }) => (
              <Select id={id} invalid={invalid} value={source} onChange={e => setSource(e.target.value)}>
                {sources.map(s => <option key={s.id} value={s.id}>{t(s.name)}</option>)}
              </Select>
            )}
          </Field>
        )}
      </form>
    </Modal>
  )
}
