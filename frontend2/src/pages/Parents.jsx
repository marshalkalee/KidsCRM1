import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Plus, Search, UsersRound } from 'lucide-react'
import api from '../api/axios'
import ParentModal from '../components/ParentModal'
import { useSession } from '../session/SessionContext'
import { Avatar, Button, DataTable, EmptyState, PageHeader, SearchInput, plural } from '../ui'

// Размер страницы — как PAGE_SIZE в DRF (config/settings/base.py).
const PAGE_SIZE = 50

export default function Parents() {
  const navigate = useNavigate()
  const { can } = useSession()
  const canManage = can('can_manage_children')
  const showPhones = can('can_view_phone')
  const [params, setParams] = useSearchParams()
  const [loaded, setLoaded] = useState({ key: null, data: { results: [], count: 0 }, error: false })
  const [reloadKey, setReloadKey] = useState(0)
  const [creating, setCreating] = useState(false)

  const q = params.get('q') || ''
  const page = Math.max(1, Number(params.get('page')) || 1)
  const requestKey = `${q}|${page}|${reloadKey}`

  useEffect(() => {
    const controller = new AbortController()
    api.get('clients/parents/', { params: { q: q || undefined, page }, signal: controller.signal })
      .then(r => setLoaded({ key: requestKey, data: r.data, error: false }))
      .catch(err => {
        if (err.name !== 'CanceledError') setLoaded(prev => ({ ...prev, key: requestKey, error: true }))
      })
    return () => controller.abort()
  }, [q, page, requestKey])

  const { data, error } = loaded
  const loading = loaded.key !== requestKey
  const setQuery = useCallback(value => setParams(value ? { q: value } : {}, { replace: true }), [setParams])

  const columns = [
    {
      key: 'full_name',
      header: 'Родитель',
      primary: true,
      render: row => (
        <div className="flex min-w-0 items-center gap-3">
          <Avatar name={row.full_name} />
          <span className="truncate font-semibold text-ink">{row.full_name}</span>
        </div>
      ),
    },
    {
      key: 'children',
      header: 'Дети',
      render: row => (row.children.length ? (
        <span className="text-ink-muted">
          {row.children.map((child, i) => (
            <span key={child.id}>
              {i > 0 && ', '}
              <Link to={`/children/${child.id}`} onClick={e => e.stopPropagation()} className="hover:text-brand-700 hover:underline">{child.full_name}</Link>
            </span>
          ))}
        </span>
      ) : <span className="text-ink-subtle">—</span>),
    },
    ...(showPhones ? [{
      key: 'phones',
      header: 'Телефон',
      render: row => (row.phones?.length
        ? <span className="whitespace-nowrap text-ink-muted">{row.phones[0].number}{row.phones.length > 1 && <span className="text-ink-subtle"> +{row.phones.length - 1}</span>}</span>
        : <span className="text-ink-subtle">—</span>),
    }] : []),
    { key: 'email', header: 'Email', hideOnMobile: true, className: 'text-ink-muted', render: row => row.email || '—' },
  ]

  return (
    <div>
      <PageHeader
        title="Родители"
        description={loading && !data.count ? 'Загрузка…' : `${data.count} ${plural(data.count, ['контакт', 'контакта', 'контактов'])}${q ? ' по запросу' : ''}`}
        actions={canManage && <Button variant="primary" icon={Plus} onClick={() => setCreating(true)}>Добавить родителя</Button>}
      />
      <div className="mb-4">
        <SearchInput value={q} onChange={setQuery} placeholder={showPhones ? 'Имя или телефон' : 'Имя родителя'} />
      </div>
      <DataTable
        columns={columns}
        rows={data.results}
        loading={loading}
        error={error}
        onRetry={() => setReloadKey(k => k + 1)}
        pagination={{ page, pageSize: PAGE_SIZE, total: data.count }}
        onPageChange={next => setParams({ ...(q ? { q } : {}), ...(next > 1 ? { page: String(next) } : {}) }, { replace: true })}
        onRowClick={row => navigate(`/parents/${row.id}`)}
        empty={q ? (
          <EmptyState icon={Search} title="Никого не нашли" description="Проверьте имя или номер телефона." />
        ) : (
          <EmptyState icon={UsersRound} title="Родителей пока нет" description="Родители появляются при добавлении контакта ребёнку или импорте из Excel." />
        )}
      />
      {creating && (
        <ParentModal onClose={() => setCreating(false)} onSaved={parent => navigate(`/parents/${parent.id}`)} />
      )}
    </div>
  )
}
