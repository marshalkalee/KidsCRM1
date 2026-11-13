import api from '../../api/axios'
import { apiErrorMessage, useToast } from '../../ui'

// Файлы для заметок: фото, документы, таблицы, текст, аудио (как в core/attachments.py).
export const ACCEPT_FILES = '.jpg,.jpeg,.png,.heic,.webp,.gif,.pdf,.doc,.docx,.xls,.xlsx,.txt,.csv,.mp3,.ogg,.opus,.m4a,.aac,.wav,.amr'

/** Открыть файл в новой вкладке (PDF, фото) или скачать (документы). */
export function useOpenFile(client = api) {
  const toast = useToast()
  return async url => {
    // Вкладку открываем сразу по клику, иначе браузер заблокирует её как всплывающее окно.
    const tab = window.open('', '_blank')
    try {
      const response = await client.get(url, { responseType: 'blob' })
      const objectUrl = URL.createObjectURL(response.data)
      if (tab) tab.location.href = objectUrl
      else window.location.href = objectUrl
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60000)
    } catch (err) {
      tab?.close()
      toast.error(apiErrorMessage(err))
    }
  }
}

/** Вложение заметки {name, content_type} → то, что понимает MediaPreview. */
export function attachmentMedia(url, file) {
  const type = file.content_type || ''
  const kind = type.startsWith('image/') && !type.includes('heic') ? 'image' : type.startsWith('audio/') ? 'audio' : 'document'
  return { url, name: file.name, kind }
}
