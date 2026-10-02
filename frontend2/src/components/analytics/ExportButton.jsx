import { useState } from 'react'
import { Download } from 'lucide-react'
import api from '../../api/axios'
import { Button, apiErrorMessage, useToast } from '../../ui'
import { t } from '../../i18n'

/**
 * «Скачать Excel» для любого отчёта (TRU-114) — одна строка на странице:
 *   <ExportButton report="revenue" filters={filters} />
 * Выгружается то, что на экране: тот же период и филиалы (filters), плюс
 * фильтры отчёта (extra — «source=…&direction=…» у воронки). Что лежит в
 * файле — описано на бэке, analytics/reports.py.
 */
export function ExportButton({ report, filters, extra = '' }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)

  async function download() {
    setBusy(true)
    try {
      const params = new URLSearchParams(filters.query)
      new URLSearchParams(extra).forEach((value, key) => params.set(key, value))
      params.set('report', report)
      const res = await api.get(`analytics/export/?${params}`, { responseType: 'blob' })
      // Имя файла — от сервера (отчёт и период), иначе — просто по отчёту.
      const match = /filename="([^"]+)"/.exec(res.headers['content-disposition'] || '')
      const url = URL.createObjectURL(res.data)
      const link = Object.assign(document.createElement('a'), { href: url, download: match?.[1] || `${report}.xlsx` })
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Button icon={Download} loading={busy} disabled={!filters.ready} onClick={download}>
      {t('Скачать Excel')}
    </Button>
  )
}
