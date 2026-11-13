import { FileText, Paperclip, Video } from 'lucide-react'
import { useEffect, useState } from 'react'
import api from '../../api/axios'
import { t } from '../../i18n'
import { useOpenFile } from './fileHelpers'

/*
 * Файлы, которые отдаёт только API (с токеном сотрудника или родителя —
 * client: axios кабинета): прямой ссылки на
 * диск нет. Картинку и аудио подгружаем в память браузера (blob), документ —
 * открываем по клику.
 */

function useBlobUrl(url, client = api) {
  const [state, setState] = useState({ url: '', failed: false })
  useEffect(() => {
    let objectUrl = ''
    let alive = true
    client.get(url, { responseType: 'blob' })
      .then(response => {
        objectUrl = URL.createObjectURL(response.data)
        if (alive) setState({ url: objectUrl, failed: false })
      })
      .catch(() => { if (alive) setState({ url: '', failed: true }) })
    return () => {
      alive = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [url, client])
  return state
}

/** Чип с именем файла — открывает по клику. */
export function FileChip({ url, name, kind, client }) {
  const open = useOpenFile(client)
  const Icon = kind === 'video' ? Video : kind === 'document' ? FileText : Paperclip
  return (
    <button type="button" onClick={() => open(url)} className="inline-flex max-w-full items-center gap-1.5 rounded-md bg-surface-muted px-2.5 py-1 text-xs font-medium text-ink hover:bg-brand-50 hover:text-brand-700">
      <Icon className="size-3.5 shrink-0" />
      <span className="truncate">{name}</span>
    </button>
  )
}

/** Картинка из API; по клику — в полном размере в новой вкладке. */
export function ProtectedImage({ url, name, client }) {
  const { url: src, failed } = useBlobUrl(url, client)
  const open = useOpenFile(client)
  if (failed) return <FileChip url={url} name={name} client={client} />
  if (!src) return <div className="h-40 w-56 animate-pulse rounded-lg bg-surface-muted" />
  return (
    <button type="button" onClick={() => open(url)} className="block overflow-hidden rounded-lg" aria-label={t('Открыть фото')}>
      <img src={src} alt={name} className="max-h-64 max-w-full object-contain" />
    </button>
  )
}

/** Аудио и голосовые — плеер прямо в сообщении. */
export function ProtectedAudio({ url, name, client }) {
  const { url: src, failed } = useBlobUrl(url, client)
  if (failed) return <FileChip url={url} name={name} client={client} />
  if (!src) return <div className="h-10 w-60 animate-pulse rounded-full bg-surface-muted" />
  return <audio controls src={src} className="h-10 w-64 max-w-full" />
}

/** Видео — плеер в сообщении; «кружочек» WhatsApp — круглый, как в телефоне. */
export function ProtectedVideo({ url, name, round = false, client }) {
  const { url: src, failed } = useBlobUrl(url, client)
  if (failed) return <FileChip url={url} name={name} kind="video" client={client} />
  if (!src) {
    return <div className={round ? 'size-48 animate-pulse rounded-full bg-surface-muted' : 'h-40 w-64 animate-pulse rounded-lg bg-surface-muted'} />
  }
  return round ? (
    <video controls playsInline src={src} className="size-48 rounded-full bg-black object-cover" />
  ) : (
    <video controls playsInline preload="metadata" src={src} className="max-h-72 w-72 max-w-full rounded-lg bg-black" />
  )
}

/** Файл сообщения: фото, видео, аудио — сразу видно и слышно, остальное — чипом. */
export function MediaPreview({ media, client }) {
  if (media.kind === 'image') return <ProtectedImage url={media.url} name={media.name} client={client} />
  if (media.kind === 'audio') return <ProtectedAudio url={media.url} name={media.name} client={client} />
  if (media.kind === 'video' || media.kind === 'video_note') {
    return <ProtectedVideo url={media.url} name={media.name} round={media.kind === 'video_note'} client={client} />
  }
  return <FileChip url={media.url} name={media.name} kind={media.kind} client={client} />
}
