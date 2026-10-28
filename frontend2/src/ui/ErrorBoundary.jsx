import { Component } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Button } from './Button'
import { EmptyState } from './Surface'
import { t } from '../i18n'

/**
 * Ошибка отрисовки страницы — сообщение вместо белого экрана. Меню и шапка
 * остаются, можно уйти на другую страницу. Сбрасывается сменой key
 * (Layout передаёт адрес страницы).
 */
export class ErrorBoundary extends Component {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error, info) {
    console.error(error, info?.componentStack)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <EmptyState
        icon={AlertTriangle}
        title={t('Не удалось открыть страницу')}
        description={t('Обновите страницу. Если ошибка повторится, сообщите в поддержку.')}
        action={<Button variant="primary" onClick={() => window.location.reload()}>{t('Обновить страницу')}</Button>}
      />
    )
  }
}
