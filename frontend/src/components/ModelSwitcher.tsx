import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bot,
  Check,
  ChevronDown,
  LoaderCircle,
  Settings2,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, jsonBody, type ModelProvider } from '../api/client'

type ProviderModel = {
  id?: string
  model?: string
  displayName?: string
  name?: string
}

export function ModelSwitcher({ bootstrapProviders }: {
  bootstrapProviders: ModelProvider[]
}) {
  const queryClient = useQueryClient()
  const root = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const providers = useQuery({
    queryKey: ['model-providers'],
    queryFn: () => api<ModelProvider[]>('/api/v1/model-providers'),
    initialData: bootstrapProviders,
  })
  const primary = providers.data?.find(
    (item) => item.role === 'primary' && item.is_enabled,
  )
  const models = useQuery({
    queryKey: ['provider-models', primary?.provider_id],
    queryFn: () => api<ProviderModel[]>(
      `/api/v1/model-providers/${primary?.provider_id}/models`,
    ),
    enabled: Boolean(primary?.provider_id && primary.available),
    retry: false,
    staleTime: 60_000,
  })
  const save = useMutation({
    mutationFn: (modelId: string) => api<ModelProvider>(
      `/api/v1/model-providers/${primary?.provider_id}`,
      {
        method: 'PATCH',
        body: jsonBody({ model_id: modelId }),
      },
    ),
    onSuccess: async () => {
      setOpen(false)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['model-providers'] }),
        queryClient.invalidateQueries({ queryKey: ['bootstrap'] }),
      ])
    },
  })

  useEffect(() => {
    if (!open) return
    function closeOnOutsideClick(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', closeOnOutsideClick)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsideClick)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])

  if (!primary) {
    return (
      <Link className="global-model-empty" to="/settings/models">
        <span className="model-orb"><Bot size={15} /></span>
        <strong>连接模型</strong>
        <ChevronDown size={14} aria-hidden="true" />
      </Link>
    )
  }

  const options = (models.data ?? []).map((item) => ({
    id: item.id ?? item.model ?? '',
    label: item.displayName ?? item.name ?? item.id ?? item.model ?? '',
  })).filter((item) => item.id)
  const current = primary.model_id ?? ''
  const currentLabel = options.find((item) => item.id === current)?.label
    ?? current
    ?? '服务默认模型'
  const busy = save.isPending || models.isPending

  return (
    <div className="model-switcher" ref={root}>
      <button
        className={`global-model-trigger${open ? ' open' : ''}`}
        type="button"
        aria-label={`当前模型：${currentLabel}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="model-orb"><Bot size={15} /></span>
        <strong className="model-current-name">{currentLabel || '正在读取模型'}</strong>
        {busy
          ? <LoaderCircle className="spin" size={15} aria-hidden="true" />
          : <ChevronDown className="model-chevron" size={15} aria-hidden="true" />}
      </button>

      {open && (
        <div className="model-menu" role="listbox" aria-label="选择当前 IELTS 模型">
          <header>
            <span className="model-live-dot" aria-hidden="true" />
            <div><strong>选择教学模型</strong><small>{primary.display_name} · 已连接</small></div>
          </header>
          <div className="model-option-list">
            {models.isPending && (
              <div className="model-menu-state"><LoaderCircle className="spin" size={16} />正在读取可用模型</div>
            )}
            {!models.isPending && options.length === 0 && (
              <div className="model-menu-state">当前服务未返回模型列表，将继续使用已配置模型。</div>
            )}
            {options.map((item) => {
              const selected = item.id === current
              return (
                <button
                  key={item.id}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  className={selected ? 'selected' : ''}
                  disabled={save.isPending}
                  onClick={() => {
                    if (!selected) save.mutate(item.id)
                    else setOpen(false)
                  }}
                >
                  <span><strong>{item.label}</strong><small>{item.id}</small></span>
                  {selected && <Check size={16} aria-hidden="true" />}
                </button>
              )
            })}
          </div>
          {save.isError && <p className="model-menu-error">切换失败，请检查模型连接后重试。</p>}
          <Link to="/settings/models" onClick={() => setOpen(false)}>
            <Settings2 size={15} />管理模型与连接
          </Link>
        </div>
      )}
    </div>
  )
}
