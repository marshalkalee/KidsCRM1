// Общие компоненты frontend2 (TRU-80) — экраны собираются из них, а не
// рисуют кнопки/таблицы/модалки заново. Цвета — токены из index.css.
export { Button } from './Button'
export { Field, Input, Select, Textarea, Checkbox } from './Field'
export { Card, CardHeader, Badge, PageHeader, EmptyState, Spinner, Skeleton, ErrorState } from './Surface'
export { Modal, ConfirmProvider, useConfirm } from './Modal'
export { ToastProvider, useToast, apiErrorMessage } from './Toast'
export { DataTable } from './DataTable'
export { cn, plural, initials } from './cn'
export { Avatar } from './Avatar'
export { money, formatDate, ageLabel, CHILD_STATUSES } from './format'
