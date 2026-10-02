import { useCallback, useEffect, useState } from 'react'
import api from '../../api/axios'
import { useSession } from '../../session/SessionContext'
import { apiErrorMessage, useConfirm, useToast } from '../../ui'
import { t } from '../../i18n'

/*
 * Переписка с ИИ (backend: ai/chat.py) — общая для вопроса на главной и
 * страницы «ИИ-помощник». Чаты хранятся на сервере (видит только автор);
 * какой открыт — помнит браузер, «Новый чат» тоже запоминается, так что
 * главная и полная версия показывают один и тот же разговор.
 */

const NEW_CHAT = 'new'

function currentKey(user) {
  return `kc-ai-chat-current:${user?.id || ''}`
}

function readCurrent(user) {
  try {
    return localStorage.getItem(currentKey(user))
  } catch {
    return null
  }
}

function writeCurrent(user, value) {
  try {
    localStorage.setItem(currentKey(user), value || NEW_CHAT)
  } catch {
    // приватное окно — откроется последний чат
  }
}

export function useAIConversation(enabled) {
  const { user } = useSession()
  const toast = useToast()
  const confirm = useConfirm()
  const [conversations, setConversations] = useState(null)
  const [currentId, setCurrentId] = useState(null)
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const startNew = useCallback(() => {
    setCurrentId(null)
    setMessages([])
    writeCurrent(user, NEW_CHAT)
  }, [user])

  const openConversation = useCallback(async id => {
    setLoading(true)
    try {
      const { data } = await api.get(`ai/conversations/${id}/`)
      setMessages(data.messages)
      setCurrentId(id)
      writeCurrent(user, id)
    } catch {
      setConversations(list => (list || []).filter(c => c.id !== id))
      startNew()
    } finally {
      setLoading(false)
    }
  }, [user, startNew])

  // Открыть чат, который был открыт в прошлый раз (или самый свежий).
  useEffect(() => {
    if (!enabled) return
    let alive = true
    api.get('ai/conversations/')
      .then(({ data }) => {
        if (!alive) return
        setConversations(data)
        const saved = readCurrent(user)
        const id = saved === NEW_CHAT ? null : data.some(c => c.id === saved) ? saved : data[0]?.id
        if (id) openConversation(id)
        else setLoading(false)
      })
      .catch(() => { if (alive) { setConversations([]); setLoading(false) } })
    return () => { alive = false }
  }, [enabled, user, openConversation])

  const send = useCallback(async text => {
    const question = (text || '').trim()
    if (!question || busy) return false
    setMessages(m => [...m.filter(x => !x.error), { role: 'user', content: question }])
    setBusy(true)
    try {
      const { data } = await api.post('ai/chat/', { message: question, conversation: currentId })
      const { id, title } = data.conversation
      setCurrentId(id)
      writeCurrent(user, id)
      setConversations(list => [{ id, title, updated_at: new Date().toISOString() }, ...(list || []).filter(c => c.id !== id)])
      setMessages(m => [...m, { role: 'assistant', content: data.answer, sources: data.sources }])
    } catch (err) {
      // Вопрос без ответа на сервере не сохранился — показываем ошибку и даём повторить.
      setMessages(m => [...m.slice(0, -1), { role: 'assistant', content: apiErrorMessage(err), error: true, retry: question }])
    } finally {
      setBusy(false)
    }
    return true
  }, [busy, currentId, user])

  const remove = useCallback(async conversation => {
    const ok = await confirm({ title: t('Удалить чат?'), message: conversation.title, confirmText: t('Удалить'), danger: true })
    if (!ok) return
    try {
      await api.delete(`ai/conversations/${conversation.id}/`)
      setConversations(list => list.filter(c => c.id !== conversation.id))
      if (conversation.id === currentId) startNew()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }, [confirm, currentId, startNew, toast])

  return { conversations, currentId, messages, loading, busy, send, startNew, openConversation, remove }
}

export function chatSuggestions(can) {
  return [
    t('Что сегодня требует внимания?'),
    t('Кто должен больше всех?'),
    t('Чьи абонементы заканчиваются на этой неделе?'),
    can('can_view_analytics') ? t('Выручка за прошлый месяц по филиалам') : t('Какие занятия сегодня?'),
    t('Какие группы заполнены меньше всего?'),
    t('Сколько новых заявок за эту неделю и откуда?'),
  ]
}
