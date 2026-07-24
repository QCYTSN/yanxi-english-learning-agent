import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, ClipboardCheck, FileArchive, FolderInput, ShieldCheck } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { api, type Question } from '../api/client'
import { ConformanceBadge, ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/Common'

type View = 'readiness' | 'library' | 'reviews' | 'imports'
type AssessmentPack = {
  pack_id: string
  title: string
  module: string
  practice_mode: string
  conformance_status: string
  local_review_status?: string
  source_type?: string
}
type ReadinessMetric = {
  key: string
  label: string
  current: number
  minimum: number
  recommended: number
  minimum_gap: number
  recommended_gap: number
  unit: string
  status: string
}
type ModuleReadiness = {
  label: string
  metrics: ReadinessMetric[]
  missing_coverage: string[]
  quality_fields: string[]
  ready_for_varied_practice: boolean
}
type Readiness = {
  modules: Record<string, ModuleReadiness>
  imports: { total: number; needs_structuring: number; ready_to_import: number; failed: number }
  band_ready_pack_count: number
}
type ImportJob = {
  import_id: string
  title: string
  source_type: string
  rights_status: string
  status: 'needs_structuring' | 'ready_to_import' | 'imported' | 'failed'
  error_message?: string | null
  created_at: string
  files: Array<{ original_name: string; file_kind: string; size_bytes: number; sha256: string }>
  summary?: { corpus_id?: string; import_result?: Record<string, number> }
}
type ReviewQueueItem = {
  target_type: 'question' | 'passage' | 'assessment_pack'
  target_id: string
  title: string
  local_review_status: string
  stale_review_count: number
}
type ReviewTarget = {
  target_type: ReviewQueueItem['target_type']
  target_id: string
  content_hash: string
  local_review_status: string
  stale_review_count: number
  required_checklist: Record<string, string>
  material: Record<string, unknown>
  dependency_status?: {
    ready: boolean
    missing_question_reviews: string[]
    missing_passage_reviews: string[]
  }
}

export function LibraryPage() {
  const [view, setView] = useState<View>('readiness')
  const [module, setModule] = useState('')
  const [query, setQuery] = useState('')
  const pageSize = 50
  const questions = useInfiniteQuery({
    queryKey: ['library', module, query],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api<Question[]>(`/api/v1/questions?limit=${pageSize}&offset=${pageParam}${module ? `&module=${module}` : ''}${query ? `&query=${encodeURIComponent(query)}` : ''}`),
    getNextPageParam: (lastPage, pages) => lastPage.length === pageSize ? pages.length * pageSize : undefined,
    enabled: view === 'library',
  })
  const packs = useInfiniteQuery({
    queryKey: ['assessment-packs', module],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api<AssessmentPack[]>(`/api/v1/assessment-packs?limit=${pageSize}&offset=${pageParam}${module ? `&module=${module}` : ''}`),
    getNextPageParam: (lastPage, pages) => lastPage.length === pageSize ? pages.length * pageSize : undefined,
    enabled: view === 'library',
  })
  const readiness = useQuery({ queryKey: ['content-readiness'], queryFn: () => api<Readiness>('/api/v1/content/readiness') })
  const imports = useQuery({ queryKey: ['content-imports'], queryFn: () => api<ImportJob[]>('/api/v1/content/imports') })
  return (
    <div className="page">
      <PageHeader eyebrow="Content" title="内容与题库" description="先登记来源和权限，再结构化、逐项审核和组套。文件自称 reviewed 不等于本地系统已经批准。" />
      <div className="segmented content-tabs" role="tablist" aria-label="内容管理视图">
        <Tab active={view === 'readiness'} onClick={() => setView('readiness')}>准备度</Tab>
        <Tab active={view === 'library'} onClick={() => setView('library')}>题库索引</Tab>
        <Tab active={view === 'reviews'} onClick={() => setView('reviews')}>人工审核</Tab>
        <Tab active={view === 'imports'} onClick={() => setView('imports')}>导入工作台</Tab>
      </div>
      {view === 'readiness' && <ReadinessView data={readiness.data} pending={readiness.isPending} error={readiness.error} />}
      {view === 'library' && <LibraryView module={module} query={query} setModule={setModule} setQuery={setQuery} questions={questions.data?.pages.flat()} packs={packs.data?.pages.flat()} pending={questions.isPending || packs.isPending} error={questions.error ?? packs.error} hasMoreQuestions={questions.hasNextPage} hasMorePacks={packs.hasNextPage} loadingMore={questions.isFetchingNextPage || packs.isFetchingNextPage} loadMoreQuestions={() => void questions.fetchNextPage()} loadMorePacks={() => void packs.fetchNextPage()} />}
      {view === 'reviews' && <ReviewWorkbench />}
      {view === 'imports' && <ImportsView jobs={imports.data ?? []} pending={imports.isPending} error={imports.error} />}
    </div>
  )
}

function Tab({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return <button role="tab" aria-selected={active} className={active ? 'active' : ''} onClick={onClick}>{children}</button>
}

function ReadinessView({ data, pending, error }: { data?: Readiness; pending: boolean; error: unknown }) {
  if (pending) return <LoadingState />
  if (error || !data) return <ErrorState error={error} />
  return <>
    <section className="content-summary-strip">
      <div><span>可换算 Band 的完整套题</span><strong>{data.band_ready_pack_count}</strong></div>
      <div><span>待结构化材料</span><strong>{data.imports.needs_structuring}</strong></div>
      <div><span>可执行结构化导入</span><strong>{data.imports.ready_to_import}</strong></div>
    </section>
    <p className="conformance-note">库存目标是本产品的训练规划值，不是 IELTS 官方规定。只有结构、权利和本地审核均有效的完整套题才能进入可信评分池。</p>
    <div className="readiness-grid">
      {Object.entries(data.modules).map(([key, item]) => <section className="readiness-card" key={key}>
        <div className="section-heading"><div><p className="eyebrow">{key}</p><h2>{item.label}</h2></div><StatusBadge tone={item.ready_for_varied_practice ? 'success' : 'warning'}>{item.ready_for_varied_practice ? '库存充足' : '需要补充'}</StatusBadge></div>
        <div className="readiness-metrics">{item.metrics.map((metric) => <div key={metric.key}><div><span>{metric.label}</span><strong>{metric.current} / {metric.minimum} {metric.unit}</strong></div><progress max={metric.minimum} value={Math.min(metric.current, metric.minimum)} /><small>{metric.minimum_gap ? `最低库存还缺 ${metric.minimum_gap}${metric.unit}；长期建议还缺 ${metric.recommended_gap}${metric.unit}` : `已达到最低库存；长期建议 ${metric.recommended}${metric.unit}`}</small></div>)}</div>
        <details><summary>查看缺少的覆盖类型</summary><p>{item.missing_coverage.length ? item.missing_coverage.join(' · ') : '基础类型均已有内容'}</p><p><strong>每份材料需要：</strong>{item.quality_fields.join(' · ')}</p></details>
      </section>)}
    </div>
  </>
}

function LibraryView({ module, query, setModule, setQuery, questions, packs, pending, error, hasMoreQuestions, hasMorePacks, loadingMore, loadMoreQuestions, loadMorePacks }: {
  module: string
  query: string
  setModule: (value: string) => void
  setQuery: (value: string) => void
  questions?: Question[]
  packs?: AssessmentPack[]
  pending: boolean
  error: unknown
  hasMoreQuestions: boolean
  hasMorePacks: boolean
  loadingMore: boolean
  loadMoreQuestions: () => void
  loadMorePacks: () => void
}) {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<string[]>([])
  const [packTitle, setPackTitle] = useState('')
  const assemble = useMutation({
    mutationFn: () => api<AssessmentPack>('/api/v1/assessment-packs', {
      method: 'POST',
      body: JSON.stringify({ module, title: packTitle, question_ids: selected }),
    }),
    onSuccess: () => {
      setSelected([])
      setPackTitle('')
      void queryClient.invalidateQueries({ queryKey: ['assessment-packs'] })
      void queryClient.invalidateQueries({ queryKey: ['content-readiness'] })
      void queryClient.invalidateQueries({ queryKey: ['content-review-queue'] })
    },
  })
  return <>
    <div className="filter-bar">
      <label>科目<select value={module} onChange={(event) => { setModule(event.target.value); setSelected([]) }}><option value="">全部</option><option value="listening">Listening</option><option value="reading">Reading</option><option value="writing">Writing</option><option value="speaking">Speaking</option></select></label>
      <label>搜索<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="主题或题目内容" /></label>
    </div>
    {module && <section className="pack-builder"><div><p className="eyebrow">Pack builder</p><h2>从已索引题目组装 {module} 套题</h2><p>Runtime 计算结构；组装完成后仍要在“人工审核”中逐项批准，再批准整套题。</p></div><label>套题名称<input value={packTitle} onChange={(event) => setPackTitle(event.target.value)} placeholder="例如：Private Reading Test 01" /></label><div><strong>{selected.length}</strong><span> 道已选</span></div><button className="button primary" disabled={!packTitle.trim() || !selected.length || assemble.isPending} onClick={() => assemble.mutate()}>组装并检查</button></section>}
    {assemble.isError && <ErrorState error={assemble.error} />}
    {pending && <LoadingState />}{error && <ErrorState error={error} />}
    {packs?.length ? <section className="library-packs"><div className="section-heading"><div><p className="eyebrow">Assessment packs</p><h2>已登记套题与分项包</h2></div></div><div className="library-grid">{packs.map((pack) => <article className="library-item" key={pack.pack_id}><div className="question-meta"><StatusBadge>{pack.source_type ?? 'unknown'}</StatusBadge><span>{pack.pack_id}</span></div><h2>{pack.title}</h2><ConformanceBadge status={pack.conformance_status} mode={pack.practice_mode} /><p>{pack.module} · 本地审核：{reviewLabel(pack.local_review_status)}</p></article>)}</div>{hasMorePacks && <button className="button secondary load-more" disabled={loadingMore} onClick={loadMorePacks}>加载更多套题</button>}</section> : null}
    <div className="section-heading library-question-heading"><div><p className="eyebrow">Items</p><h2>单题与练习材料</h2></div></div>
    <div className="library-grid">{questions?.map((question) => <article className={`library-item ${selected.includes(question.question_id) ? 'selected' : ''}`} key={question.question_id}>{module && <label className="pack-select"><input type="checkbox" checked={selected.includes(question.question_id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, question.question_id] : current.filter((value) => value !== question.question_id))} />加入套题</label>}<div className="question-meta"><StatusBadge>{question.source_type ?? 'unknown'}</StatusBadge><span>{question.question_id}</span></div><h2>{question.content}</h2><ConformanceBadge status={question.conformance_status} mode={question.practice_mode} /><p>{question.module} · {question.task ?? question.question_type ?? 'practice'} · 本地审核：{reviewLabel(String(question.local_review_status ?? 'unreviewed'))}</p></article>)}</div>
    {hasMoreQuestions && <button className="button secondary load-more" disabled={loadingMore} onClick={loadMoreQuestions}>加载更多题目</button>}
  </>
}

function ReviewWorkbench() {
  const queryClient = useQueryClient()
  const [targetType, setTargetType] = useState('')
  const [selected, setSelected] = useState<ReviewQueueItem | null>(null)
  const [reviewer, setReviewer] = useState('Local content reviewer')
  const [notes, setNotes] = useState('')
  const [checklist, setChecklist] = useState<Record<string, boolean>>({})
  const queue = useQuery({
    queryKey: ['content-review-queue', targetType],
    queryFn: () => api<ReviewQueueItem[]>(`/api/v1/content-reviews/queue?limit=200${targetType ? `&target_type=${targetType}` : ''}`),
  })
  const detail = useQuery({
    queryKey: ['content-review-target', selected?.target_type, selected?.target_id],
    queryFn: () => api<ReviewTarget>(`/api/v1/content-reviews/targets/${selected?.target_type}/${selected?.target_id}`),
    enabled: Boolean(selected),
  })
  useEffect(() => {
    if (!detail.data) return
    setChecklist(Object.fromEntries(Object.keys(detail.data.required_checklist).map((key) => [key, false])))
    setNotes('')
  }, [detail.data])
  const submit = useMutation({
    mutationFn: (decision: 'approved' | 'changes_requested' | 'rejected') => {
      if (!selected) throw new Error('请先选择审核对象')
      return api<ReviewTarget>(`/api/v1/content-reviews/targets/${selected.target_type}/${selected.target_id}`, {
        method: 'POST',
        body: JSON.stringify({ reviewer, decision, checklist, notes: notes || null }),
      })
    },
    onSuccess: () => {
      setSelected(null)
      void queryClient.invalidateQueries({ queryKey: ['content-review-queue'] })
      void queryClient.invalidateQueries({ queryKey: ['content-review-target'] })
      void queryClient.invalidateQueries({ queryKey: ['library'] })
      void queryClient.invalidateQueries({ queryKey: ['assessment-packs'] })
      void queryClient.invalidateQueries({ queryKey: ['content-readiness'] })
    },
  })
  const allChecked = detail.data && Object.keys(detail.data.required_checklist).every((key) => checklist[key])
  return <div className="review-workbench">
    <section className="settings-section review-queue">
      <div className="section-heading"><div><p className="eyebrow">Local approval</p><h2>待审核内容</h2></div><ClipboardCheck /></div>
      <label>类型<select value={targetType} onChange={(event) => { setTargetType(event.target.value); setSelected(null) }}><option value="">全部</option><option value="question">题目</option><option value="passage">文章</option><option value="assessment_pack">套题</option></select></label>
      {queue.isPending && <LoadingState />}{queue.error && <ErrorState error={queue.error} />}
      {!queue.isPending && !queue.data?.length && <p className="muted">当前没有待审核内容。</p>}
      <div className="review-queue-list">{queue.data?.map((item) => <button key={`${item.target_type}:${item.target_id}`} className={selected?.target_id === item.target_id ? 'active' : ''} onClick={() => setSelected(item)}><span><strong>{item.title}</strong><small>{item.target_type} · {item.target_id}</small></span><StatusBadge tone={item.local_review_status === 'stale' ? 'warning' : 'neutral'}>{reviewLabel(item.local_review_status)}</StatusBadge></button>)}</div>
    </section>
    <section className="settings-section review-detail">
      {!selected && <div className="empty-state"><ClipboardCheck /><h2>选择一项开始审核</h2><p>批准记录会绑定完整内容哈希；内容变化后不会沿用旧结论。</p></div>}
      {detail.isPending && selected && <LoadingState />}
      {detail.error && <ErrorState error={detail.error} />}
      {detail.data && <>
        <div className="section-heading"><div><p className="eyebrow">{detail.data.target_type}</p><h2>{detail.data.target_id}</h2></div><StatusBadge>{reviewLabel(detail.data.local_review_status)}</StatusBadge></div>
        <small>内容指纹：{detail.data.content_hash.slice(0, 16)}…</small>
        <ReviewMaterial material={detail.data.material} />
        {detail.data.dependency_status && !detail.data.dependency_status.ready && <div className="import-boundary"><ShieldCheck /><p>整套题还缺少本地批准：{[...detail.data.dependency_status.missing_question_reviews, ...detail.data.dependency_status.missing_passage_reviews].join('、')}</p></div>}
        <label>审核人<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label>
        <div className="review-checklist">{Object.entries(detail.data.required_checklist).map(([key, label]) => <label key={key}><input type="checkbox" checked={Boolean(checklist[key])} onChange={(event) => setChecklist((current) => ({ ...current, [key]: event.target.checked }))} />{label}</label>)}</div>
        <label>审核备注<textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="记录核对依据、待修改问题或拒绝原因" /></label>
        {submit.isError && <ErrorState error={submit.error} />}
        <div className="review-actions"><button className="button primary" disabled={!reviewer.trim() || !allChecked || submit.isPending || detail.data.dependency_status?.ready === false} onClick={() => submit.mutate('approved')}>批准并进入可信池</button><button className="button secondary" disabled={!reviewer.trim() || submit.isPending} onClick={() => submit.mutate('changes_requested')}>退回修改</button><button className="button ghost" disabled={!reviewer.trim() || submit.isPending} onClick={() => submit.mutate('rejected')}>拒绝</button></div>
      </>}
    </section>
  </div>
}

function ReviewMaterial({ material }: { material: Record<string, unknown> }) {
  const options = material.options
  return <div className="review-material">
    {Boolean(material.title) && <h3>{String(material.title)}</h3>}
    {Boolean(material.content) && <p className="review-prompt">{String(material.content)}</p>}
    {Boolean(material.body) && <div className="review-passage">{String(material.body)}</div>}
    {Boolean(material.passage) && typeof material.passage === 'object' && <div className="review-passage">{String((material.passage as Record<string, unknown>).body ?? '')}</div>}
    {Boolean(options) && <pre>{JSON.stringify(options, null, 2)}</pre>}
    {material.correct_answer !== undefined && <p><strong>答案：</strong>{JSON.stringify(material.correct_answer)}</p>}
    {Boolean(material.evidence_location) && <p><strong>证据位置：</strong>{String(material.evidence_location)}</p>}
    {Boolean(material.explanation) && <p><strong>解释：</strong>{String(material.explanation)}</p>}
    {Boolean(material.structure) && <pre>{JSON.stringify(material.structure, null, 2)}</pre>}
  </div>
}

function ImportsView({ jobs, pending, error }: { jobs: ImportJob[]; pending: boolean; error: unknown }) {
  const queryClient = useQueryClient()
  const [title, setTitle] = useState('')
  const [sourceType, setSourceType] = useState('licensed_private')
  const [authenticity, setAuthenticity] = useState('unreviewed')
  const [selected, setSelected] = useState<File[]>([])
  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData()
      form.append('title', title)
      form.append('source_type', sourceType)
      form.append('authenticity', authenticity)
      form.append('rights_status', sourceType === 'project_original' ? 'redistributable' : 'local_private')
      selected.forEach((file) => form.append('files', file))
      return api<ImportJob>('/api/v1/content/imports', { method: 'POST', body: form })
    },
    onSuccess: () => {
      setTitle('')
      setSelected([])
      void queryClient.invalidateQueries({ queryKey: ['content-imports'] })
      void queryClient.invalidateQueries({ queryKey: ['content-readiness'] })
    },
  })
  const process = useMutation({
    mutationFn: (importId: string) => api<ImportJob>(`/api/v1/content/imports/${importId}/process`, { method: 'POST' }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['content-imports'] })
      void queryClient.invalidateQueries({ queryKey: ['content-readiness'] })
      void queryClient.invalidateQueries({ queryKey: ['library'] })
      void queryClient.invalidateQueries({ queryKey: ['content-review-queue'] })
    },
  })
  return <div className="imports-layout">
    <section className="settings-section import-form">
      <p className="eyebrow">Local inbox</p><h2>登记本地学习材料</h2>
      <div className="import-boundary"><ShieldCheck /><p>PDF、图片和音频只进入本地待结构化队列；只有包含 <code>manifest.yaml</code> 与对应 JSONL 的包才能执行正式导入。</p></div>
      <label>材料名称<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：我合法持有的练习册 01" /></label>
      <div className="handoff-options">
        <label>来源<select value={sourceType} onChange={(event) => setSourceType(event.target.value)}><option value="licensed_private">合法持有 · 私人材料</option><option value="official_external">官方外部链接材料</option><option value="seasonal_reported">民间回忆 · 未验证</option><option value="personal">个人创建</option><option value="synthetic">合成练习</option><option value="project_original">项目原创</option></select></label>
        <label>真实性说明<input value={authenticity} onChange={(event) => setAuthenticity(event.target.value)} placeholder="official_practice_book / practice_only" /></label>
      </div>
      <label className="file-drop"><FolderInput /><span>{selected.length ? `已选择 ${selected.length} 个文件` : '选择 PDF、音频、图片，或 manifest + JSONL'}</span><input type="file" multiple accept=".pdf,.yaml,.yml,.json,.jsonl,.png,.jpg,.jpeg,.webp,.mp3,.wav,.m4a" onChange={(event) => setSelected(Array.from(event.target.files ?? []))} /></label>
      <button className="button primary" disabled={!title.trim() || !selected.length || upload.isPending} onClick={() => upload.mutate()}>上传到本地队列</button>
      {upload.isError && <ErrorState error={upload.error} />}
    </section>
    <section className="settings-section import-queue">
      <div className="section-heading"><div><p className="eyebrow">Queue</p><h2>材料处理状态</h2></div></div>
      {pending && <LoadingState />}{Boolean(error) && <ErrorState error={error} />}{process.isError && <ErrorState error={process.error} />}
      {!pending && !jobs.length && <p className="muted">还没有上传材料。</p>}
      {jobs.map((job) => <article key={job.import_id} className="import-job"><div className="import-job-heading"><FileArchive /><div><strong>{job.title}</strong><small>{job.import_id} · {job.files.length} 个文件</small></div><ImportStatus status={job.status} /></div><p>{job.files.map((file) => file.original_name).join(' · ')}</p>{job.error_message && <p className="import-error">{job.error_message}</p>}{job.status === 'ready_to_import' && <button className="button secondary" disabled={process.isPending} onClick={() => process.mutate(job.import_id)}><CheckCircle2 size={17} />验证并导入</button>}{job.status === 'needs_structuring' && <small>下一步：整理为 passages/questions/assessment_packs JSONL，并补充 Manifest。</small>}</article>)}
    </section>
  </div>
}

function ImportStatus({ status }: { status: ImportJob['status'] }) {
  const labels = { needs_structuring: '待结构化', ready_to_import: '可验证导入', imported: '已导入', failed: '导入失败' }
  return <StatusBadge tone={status === 'imported' ? 'success' : status === 'failed' ? 'warning' : 'neutral'}>{labels[status]}</StatusBadge>
}

function reviewLabel(status?: string) {
  return ({ approved: '已批准', stale: '审核已过期', changes_requested: '待修改', rejected: '已拒绝', unreviewed: '未审核' } as Record<string, string>)[status ?? 'unreviewed'] ?? status
}
