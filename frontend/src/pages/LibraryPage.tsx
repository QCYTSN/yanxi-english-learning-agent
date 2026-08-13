import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, CheckCircle2, ClipboardCheck, FileArchive, FolderCog, FolderInput, ShieldCheck } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type Question } from '../api/client'
import { ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/Common'

type View = 'readiness' | 'reviews' | 'assembly' | 'imports'
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
  status: 'needs_structuring' | 'queued' | 'preparing' | 'ocr_queued' | 'ocr_running' | 'ready_for_review' | 'draft_building' | 'draft_ready' | 'ready_to_import' | 'imported' | 'failed'
  error_message?: string | null
  created_at: string
  updated_at?: string
  files: Array<{
    original_name: string
    stored_name: string
    file_kind: 'pdf' | 'audio' | 'image' | 'text' | 'document' | 'structured'
    mime_type?: string | null
    size_bytes: number
    sha256: string
  }>
  summary?: {
    corpus_id?: string
    import_result?: Record<string, number>
    preparation?: {
      status?: string
      progress?: number
      page_count?: number
      needs_ocr_pages?: number
      recovery_action?: string | null
    }
    documents?: ImportDocument[]
    page_plan?: Record<string, Record<string, PageRole>>
    ocr?: {
      status?: string
      stored_name?: string
      pages?: number[]
      progress?: number
      processed_pages?: number
      recovery_action?: string | null
    }
    review_draft?: {
      status?: string
      progress?: number
      segment_count?: number
      reviewed_segment_count?: number
      revision?: number
      recovery_action?: string | null
    }
    structured_package?: {
      status?: string
      corpus_id?: string
      passage_count?: number
      question_count?: number
      assessment_pack_count?: number
      module_counts?: Record<string, number>
      skipped?: Array<{ module: string; test: number; reason: string }>
      provisional?: boolean
    }
  }
}
type OcrRuntime = {
  engine_id: string
  display_name: string
  status: 'not_installed' | 'queued' | 'installing' | 'ready' | 'failed'
  available: boolean
  local_only: boolean
  isolated: boolean
  error_message?: string | null
  recovery_action?: string | null
  max_pages_per_run: number
}
type ContentStorage = {
  quota_bytes: number
  used_bytes: number
  remaining_bytes: number
  usage_ratio: number
  over_quota: boolean
  max_file_bytes: number
  max_import_bytes: number
}
type ReviewDraftSegment = {
  segment_id: string
  role: PageRole
  stored_name: string
  page_start: number
  page_end: number
  page_numbers: number[]
  text: string
  text_hash: string
  review_status: 'needs_review' | 'reviewed' | 'excluded'
  eligible_for_import: false
}
type ReviewDraft = {
  draft_version: number
  revision: number
  import_id: string
  title: string
  review_status: string
  eligible_for_import: false
  review_issues?: Array<{
    issue_id: string
    code: string
    severity: 'info' | 'warning' | 'blocker'
    message: string
    page_numbers: number[]
    evidence: string
    status: 'open' | 'resolved'
  }>
  segments: ReviewDraftSegment[]
}
type AudioCue = {
  cue_id?: string | null
  start_seconds: number
  end_seconds: number
  text: string
}
type AudioReview = {
  audio_review_version: number
  revision: number
  import_id: string
  stored_name: string
  original_name?: string
  duration_seconds?: number | null
  transcript: string
  cues: AudioCue[]
  review_status: 'needs_review' | 'reviewed'
  eligible_for_import: false
}
type PageRole = 'unassigned' | 'passage' | 'questions' | 'reading_test' | 'reading_passage' | 'reading_questions' | 'writing_task_1' | 'writing_task_2' | 'answer_key_with_writing_task_1' | 'writing_task_2_with_task_1_visual' | 'speaking_test' | 'speaking_test_with_sample_answers' | 'answer_key' | 'task_visual' | 'transcript' | 'instructions' | 'exclude'
type ImportDocument = {
  stored_name: string
  file_kind: string
  status: string
  page_count: number
  needs_ocr_pages?: number
  pages?: Array<{
    page_number: number
    text_chars: number
    text_preview: string
    extraction_status: 'text_available' | 'ocr_available' | 'ocr_required' | 'error'
    text_source?: 'pdf_text' | 'ocr' | 'text' | 'document' | 'none'
    ocr_confidence?: number | null
    error?: string | null
  }>
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
  const [module, setModule] = useState('')
  const [query, setQuery] = useState('')
  const pageSize = 50
  const questions = useInfiniteQuery({
    queryKey: ['library', module, query],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api<Question[]>(`/api/v1/questions?limit=${pageSize}&offset=${pageParam}${module ? `&module=${module}` : ''}${query ? `&query=${encodeURIComponent(query)}` : ''}`),
    getNextPageParam: (lastPage, pages) => lastPage.length === pageSize ? pages.length * pageSize : undefined,
  })
  return (
    <div className="page page-library">
      <PageHeader
        eyebrow="学习资料库"
        title="选择材料，直接开始练习"
        description="这里只展示学习者需要的题目与套题；导入、结构化和审核集中到独立内容工作台。"
        action={<Link className="button secondary" to="/content-studio"><FolderCog size={17} />管理本地材料</Link>}
      />
      <LibraryView
        module={module}
        query={query}
        setModule={setModule}
        setQuery={setQuery}
        questions={questions.data?.pages.flat()}
        pending={questions.isPending}
        error={questions.error}
        hasMoreQuestions={questions.hasNextPage}
        loadingMore={questions.isFetchingNextPage}
        loadMoreQuestions={() => void questions.fetchNextPage()}
      />
    </div>
  )
}

export function ContentStudioPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const promotedImportId = searchParams.get('import')
  const imports = useQuery({
    queryKey: ['content-imports'],
    queryFn: () => api<ImportJob[]>('/api/v1/content/imports'),
    refetchInterval: (query) => {
      const active = query.state.data?.some((job) => ['queued', 'preparing', 'ocr_queued', 'ocr_running', 'draft_building'].includes(job.status))
      return active ? 1_500 : false
    },
  })
  return (
    <div className="page page-content-studio">
      <PageHeader
        eyebrow="本地内容工作台"
        title="整理原始材料"
        description="来源登记、PDF 页级整理和正式导入在这里完成；原始文件不会直接进入学习题库。"
        action={<Link className="button secondary" to="/library">返回学习资料库</Link>}
      />
      <ImportsView jobs={imports.data ?? []} pending={imports.isPending} error={imports.error} initialSelectedImportId={promotedImportId} />
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
    <p className="conformance-note">库存目标是本产品的训练规划值，不是考试官方规定。只有结构、权利和本地审核均有效的完整套题才能进入可信评分池。</p>
    <div className="readiness-grid">
      {Object.entries(data.modules).map(([key, item]) => <section className="readiness-card" key={key}>
        <div className="section-heading"><div><p className="eyebrow">{key}</p><h2>{item.label}</h2></div><StatusBadge tone={item.ready_for_varied_practice ? 'success' : 'warning'}>{item.ready_for_varied_practice ? '库存充足' : '需要补充'}</StatusBadge></div>
        <div className="readiness-metrics">{item.metrics.map((metric) => <div key={metric.key}><div><span>{metric.label}</span><strong>{metric.current} / {metric.minimum} {metric.unit}</strong></div><progress max={metric.minimum} value={Math.min(metric.current, metric.minimum)} /><small>{metric.minimum_gap ? `最低库存还缺 ${metric.minimum_gap}${metric.unit}；长期建议还缺 ${metric.recommended_gap}${metric.unit}` : `已达到最低库存；长期建议 ${metric.recommended}${metric.unit}`}</small></div>)}</div>
        <details><summary>查看缺少的覆盖类型</summary><p>{item.missing_coverage.length ? item.missing_coverage.join(' · ') : '基础类型均已有内容'}</p><p><strong>每份材料需要：</strong>{item.quality_fields.join(' · ')}</p></details>
      </section>)}
    </div>
  </>
}

function LibraryView({ module, query, setModule, setQuery, questions, pending, error, hasMoreQuestions, loadingMore, loadMoreQuestions }: {
  module: string
  query: string
  setModule: (value: string) => void
  setQuery: (value: string) => void
  questions?: Question[]
  pending: boolean
  error: unknown
  hasMoreQuestions: boolean
  loadingMore: boolean
  loadMoreQuestions: () => void
}) {
  return <>
    <div className="filter-bar">
      <label>科目<select value={module} onChange={(event) => setModule(event.target.value)}><option value="">全部</option><option value="listening">Listening</option><option value="reading">Reading</option><option value="writing">Writing</option><option value="speaking">Speaking</option></select></label>
      <label>搜索<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="主题或题目内容" /></label>
    </div>
    {pending && <LoadingState />}{error && <ErrorState error={error} />}
    <div className="section-heading library-question-heading"><div><h2>单题与练习材料</h2></div></div>
    <div className="library-grid">{questions?.map((question) => <article className="library-item" key={question.question_id}><div className="library-item-copy"><div className="question-meta"><StatusBadge>{question.source_type ?? '本地材料'}</StatusBadge><span>{question.task ?? question.question_type ?? question.module}</span></div><h2>{question.content}</h2><p>{question.module} · {question.task ?? question.question_type ?? 'practice'} · 内容已通过本地审核</p></div><Link className="library-open-action" to={`/practice?module=${question.module}`} aria-label={`练习 ${question.content}`}>去练习 <ArrowRight size={16} /></Link></article>)}</div>
    {hasMoreQuestions && <button className="button secondary load-more" disabled={loadingMore} onClick={loadMoreQuestions}>加载更多题目</button>}
  </>
}

function PackAssemblyView() {
  const queryClient = useQueryClient()
  const [module, setModule] = useState('reading')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [packTitle, setPackTitle] = useState('')
  const questions = useQuery({
    queryKey: ['pack-assembly-questions', module, query],
    queryFn: () => api<Question[]>(`/api/v1/questions?review_mode=true&limit=500&module=${module}${query ? `&query=${encodeURIComponent(query)}` : ''}`),
  })
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
  return <section className="pack-assembly-view">
    <div className="section-heading">
      <div><h2>把已索引题目组成一套练习</h2><p>组装后仍需在“人工审核”中逐项批准，再批准整套题。</p></div>
      <strong>{selected.length} 道已选</strong>
    </div>
    <div className="filter-bar">
      <label>科目<select value={module} onChange={(event) => { setModule(event.target.value); setSelected([]) }}><option value="listening">Listening</option><option value="reading">Reading</option><option value="writing">Writing</option><option value="speaking">Speaking</option></select></label>
      <label>搜索<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="主题或题目内容" /></label>
    </div>
    <div className="pack-assembly-bar">
      <label>套题名称<input value={packTitle} onChange={(event) => setPackTitle(event.target.value)} placeholder="例如：Private Reading Test 01" /></label>
      <button className="button primary" disabled={!packTitle.trim() || !selected.length || assemble.isPending} onClick={() => assemble.mutate()}>组装并检查</button>
    </div>
    {questions.isPending && <LoadingState />}
    {questions.error && <ErrorState error={questions.error} />}
    {assemble.error && <ErrorState error={assemble.error} />}
    <div className="assembly-question-list">{questions.data?.map((question) => <label className={selected.includes(question.question_id) ? 'selected' : ''} key={question.question_id}><input type="checkbox" checked={selected.includes(question.question_id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, question.question_id] : current.filter((value) => value !== question.question_id))} /><span><strong>{question.content}</strong><small>{question.question_id} · {question.task ?? question.question_type ?? question.module}</small></span></label>)}</div>
  </section>
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

function ImportsView({ jobs, pending, error, initialSelectedImportId }: {
  jobs: ImportJob[]
  pending: boolean
  error: unknown
  initialSelectedImportId?: string | null
}) {
  const queryClient = useQueryClient()
  const [title, setTitle] = useState('')
  const [sourceType, setSourceType] = useState('licensed_private')
  const [authenticity, setAuthenticity] = useState('unreviewed')
  const [selected, setSelected] = useState<File[]>([])
  const [selectedImportId, setSelectedImportId] = useState<string | null>(
    initialSelectedImportId ?? null,
  )
  const [selectedJobIds, setSelectedJobIds] = useState<string[]>([])
  const detail = useQuery({
    queryKey: ['content-import', selectedImportId],
    queryFn: () => api<ImportJob>(`/api/v1/content/imports/${selectedImportId}`),
    enabled: Boolean(selectedImportId),
    refetchInterval: (query) => (
      ['queued', 'preparing', 'ocr_queued', 'ocr_running', 'draft_building'].includes(query.state.data?.status ?? '') ? 1_500 : false
    ),
  })
  const ocrRuntime = useQuery({
    queryKey: ['content-ocr-runtime'],
    queryFn: () => api<OcrRuntime>('/api/v1/content/ocr-runtime'),
    refetchInterval: (query) => (
      ['queued', 'installing'].includes(query.state.data?.status ?? '') ? 2_000 : false
    ),
  })
  const storage = useQuery({
    queryKey: ['content-storage'],
    queryFn: () => api<ContentStorage>('/api/v1/content/storage'),
  })
  useEffect(() => {
    if (initialSelectedImportId) setSelectedImportId(initialSelectedImportId)
  }, [initialSelectedImportId])
  const refresh = async (importId?: string) => {
    await queryClient.invalidateQueries({ queryKey: ['content-imports'] })
    await queryClient.invalidateQueries({ queryKey: ['content-readiness'] })
    await queryClient.invalidateQueries({ queryKey: ['content-storage'] })
    if (importId) await queryClient.invalidateQueries({ queryKey: ['content-import', importId] })
  }
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
    onSuccess: (job) => {
      setTitle('')
      setSelected([])
      setSelectedImportId(job.import_id)
      void refresh(job.import_id)
    },
  })
  const prepare = useMutation({
    mutationFn: (importId: string) => api<ImportJob>(`/api/v1/content/imports/${importId}/prepare`, { method: 'POST' }),
    onSuccess: (job) => {
      setSelectedImportId(job.import_id)
      void refresh(job.import_id)
    },
  })
  const process = useMutation({
    mutationFn: (importId: string) => api<ImportJob>(`/api/v1/content/imports/${importId}/process`, { method: 'POST' }),
    onSuccess: (job) => {
      void refresh(job.import_id)
      void queryClient.invalidateQueries({ queryKey: ['library'] })
      void queryClient.invalidateQueries({ queryKey: ['content-review-queue'] })
    },
  })
  const buildPackage = useMutation({
    mutationFn: (importId: string) => api(
      `/api/v1/content/imports/${importId}/structured-package`,
      { method: 'POST' },
    ),
    onSuccess: () => void refresh(),
  })
  const installOcr = useMutation({
    mutationFn: () => api<OcrRuntime>('/api/v1/content/ocr-runtime/install', { method: 'POST' }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['content-ocr-runtime'] }),
  })
  const batchProcess = useMutation({
    mutationFn: async (action: 'prepare' | 'draft' | 'import') => {
      const selectedJobs = jobs.filter((job) => selectedJobIds.includes(job.import_id))
      const endpoints = selectedJobs.flatMap((job) => {
        if (action === 'prepare' && (job.status === 'needs_structuring' || job.summary?.preparation?.recovery_action === 'retry_preparation')) {
          return [`/api/v1/content/imports/${job.import_id}/prepare`]
        }
        if (action === 'draft' && ['ready_for_review', 'draft_ready', 'failed'].includes(job.status)) {
          return [`/api/v1/content/imports/${job.import_id}/review-draft`]
        }
        if (action === 'import' && job.status === 'ready_to_import') {
          return [`/api/v1/content/imports/${job.import_id}/process`]
        }
        return []
      })
      if (!endpoints.length) throw new Error('所选材料中没有适用于这项批量操作的任务。')
      const results = await Promise.allSettled(endpoints.map((endpoint) => api(endpoint, { method: 'POST' })))
      const failed = results.filter((result) => result.status === 'rejected')
      if (failed.length) throw new Error(`${results.length - failed.length} 项已启动，${failed.length} 项失败；请查看各材料状态。`)
      return results.length
    },
    onSettled: () => void refresh(),
  })
  const batchDelete = useMutation({
    mutationFn: async () => {
      const deletable = jobs
        .filter((job) => selectedJobIds.includes(job.import_id))
        .filter((job) => !['imported', 'queued', 'preparing', 'ocr_queued', 'ocr_running', 'draft_building'].includes(job.status))
        .map((job) => job.import_id)
      if (!deletable.length) throw new Error('所选材料中没有可以删除的未导入任务。')
      if (!window.confirm(`确定永久删除 ${deletable.length} 个本地待处理材料及其文件吗？此操作用于释放磁盘空间，无法撤销。`)) {
        return null
      }
      return api<{ deleted: Array<{ import_id: string }>; failed: Array<{ import_id: string; error: string }>; storage: ContentStorage }>('/api/v1/content/imports/batch-delete', {
        method: 'POST',
        body: JSON.stringify({ import_ids: deletable, confirmed: true }),
        headers: { 'Content-Type': 'application/json' },
      })
    },
    onSuccess: async (result) => {
      if (!result) return
      const deletedIds = new Set(result.deleted.map((item) => item.import_id))
      setSelectedJobIds((current) => current.filter((id) => !deletedIds.has(id)))
      if (selectedImportId && deletedIds.has(selectedImportId)) setSelectedImportId(null)
      await refresh()
    },
  })
  return <div className="imports-layout">
    <section className="settings-section import-form">
      <p className="eyebrow">Local inbox</p><h2>登记本地学习材料</h2>
      <div className="import-boundary"><ShieldCheck /><p>PDF、图片和音频只进入本地待结构化队列；只有包含 <code>manifest.yaml</code> 与对应 JSONL 的包才能执行正式导入。</p></div>
      {storage.data && (
        <div className="content-storage-meter">
          <div><span>本地材料空间</span><strong>{formatBytes(storage.data.used_bytes)} / {formatBytes(storage.data.quota_bytes)}</strong></div>
          <progress max={1} value={Math.min(1, storage.data.usage_ratio)} />
          <small>单个文件最多 {formatBytes(storage.data.max_file_bytes)}；单次导入最多 {formatBytes(storage.data.max_import_bytes)}。</small>
        </div>
      )}
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
      <div className="section-heading">
        <div><p className="eyebrow">Queue</p><h2>材料处理状态</h2></div>
        <span>{selectedJobIds.length ? `已选 ${selectedJobIds.length} 项` : '可多选批量处理'}</span>
      </div>
      <div className="content-batch-actions">
        <button className="button secondary" disabled={!selectedJobIds.length || batchProcess.isPending} onClick={() => batchProcess.mutate('prepare')}>批量分析 PDF</button>
        <button className="button secondary" disabled={!selectedJobIds.length || batchProcess.isPending} onClick={() => batchProcess.mutate('draft')}>批量生成草稿</button>
        <button className="button secondary" disabled={!selectedJobIds.length || batchProcess.isPending} onClick={() => batchProcess.mutate('import')}>批量验证导入</button>
        <button className="button ghost" disabled={!selectedJobIds.length || batchDelete.isPending} onClick={() => batchDelete.mutate()}>批量删除未导入材料</button>
      </div>
      <div className="ocr-runtime-card">
        <div>
          <strong>扫描件与截图文字识别</strong>
          <small>
            {ocrRuntime.data?.available
              ? '隔离的本地 OCR 已就绪；材料不会发送到远程服务。'
              : ocrRuntime.data?.status === 'installing' || ocrRuntime.data?.status === 'queued'
                ? '正在独立环境中安装，不影响主学习系统。'
                : '仅扫描型 PDF 和截图需要；普通可选中文字的 PDF 无需安装。'}
          </small>
        </div>
        {!ocrRuntime.data?.available && (
          <button
            className="button secondary"
            disabled={installOcr.isPending || ['queued', 'installing'].includes(ocrRuntime.data?.status ?? '')}
            onClick={() => installOcr.mutate()}
          >
            {ocrRuntime.data?.status === 'failed' ? '重试安装本地 OCR' : '安装本地 OCR'}
          </button>
        )}
      </div>
      {(ocrRuntime.error || installOcr.error || ocrRuntime.data?.error_message) && (
        <ErrorState error={ocrRuntime.error ?? installOcr.error ?? new Error(ocrRuntime.data?.error_message ?? '')} />
      )}
      {pending && <LoadingState />}{Boolean(error) && <ErrorState error={error} />}
      {(prepare.isError || buildPackage.isError || process.isError || batchProcess.isError || batchDelete.isError) && <ErrorState error={prepare.error ?? buildPackage.error ?? process.error ?? batchProcess.error ?? batchDelete.error} />}
      {!pending && !jobs.length && <p className="muted">还没有上传材料。</p>}
      {jobs.map((job) => (
        <article key={job.import_id} className={selectedImportId === job.import_id ? 'import-job active' : 'import-job'}>
          <div className="import-job-heading">
            <input
              type="checkbox"
              aria-label={`选择 ${job.title}`}
              checked={selectedJobIds.includes(job.import_id)}
              onChange={(event) => setSelectedJobIds((current) => event.target.checked ? [...current, job.import_id] : current.filter((id) => id !== job.import_id))}
            />
            <FileArchive />
            <div><strong>{job.title}</strong><small>{job.import_id} · {job.files.length} 个文件</small></div>
            <ImportStatus status={job.status} />
          </div>
          <p>{job.files.map((file) => file.original_name).join(' · ')}</p>
          {job.summary?.preparation && (
            <div className="import-progress">
              <progress max={100} value={job.summary.preparation.progress ?? 0} />
              <small>
                {job.summary.preparation.page_count ?? 0} 页
                {job.summary.preparation.needs_ocr_pages ? ` · ${job.summary.preparation.needs_ocr_pages} 页需要 OCR` : ''}
              </small>
            </div>
          )}
          {job.error_message && <p className="import-error">{job.error_message}</p>}
          <div className="row-actions">
            {(job.status === 'needs_structuring' || (job.status === 'failed' && job.summary?.preparation?.recovery_action === 'retry_preparation')) && job.files.some((file) => ['pdf', 'image', 'text', 'document'].includes(file.file_kind)) && (
              <button className="button secondary" disabled={prepare.isPending} onClick={() => prepare.mutate(job.import_id)}>
                {job.status === 'failed' ? '重试材料分析' : '开始材料页级分析'}
              </button>
            )}
            {(['ready_for_review', 'draft_ready'] as ImportJob['status'][]).includes(job.status) && (
              <button className="button secondary" onClick={() => setSelectedImportId(job.import_id)}>查看页级整理</button>
            )}
            {job.status === 'draft_ready' && (
              <button
                className="button primary"
                disabled={buildPackage.isPending}
                onClick={() => buildPackage.mutate(job.import_id)}
              >
                生成私有结构化题库
              </button>
            )}
            {job.status === 'failed' && job.summary?.documents?.some((item) => ['pdf', 'image', 'text', 'document'].includes(item.file_kind)) && job.summary?.preparation?.recovery_action !== 'retry_preparation' && (
              <button className="button secondary" onClick={() => setSelectedImportId(job.import_id)}>查看并恢复</button>
            )}
            {job.status === 'ready_to_import' && (
              <button className="button secondary" disabled={process.isPending} onClick={() => process.mutate(job.import_id)}>
                <CheckCircle2 size={17} />验证并导入
              </button>
            )}
          </div>
          {job.summary?.structured_package && (
            <small>
              已生成 {job.summary.structured_package.question_count ?? 0} 道结构化题目；
              未完成本地人工批准前只作为临时练习内容。
            </small>
          )}
          {job.status === 'needs_structuring' && !job.files.some((file) => ['pdf', 'image', 'text', 'document'].includes(file.file_kind)) && (
            <small>当前文件需要整理为 passages/questions/assessment_packs JSONL，并补充 Manifest。</small>
          )}
        </article>
      ))}
    </section>
    {selectedImportId && (
      <section className="content-import-detail">
        {detail.isPending && <LoadingState label="正在读取页级结构" />}
        {detail.error && <ErrorState error={detail.error} />}
        {detail.data && <ImportDetailPanel job={detail.data} ocrRuntime={ocrRuntime.data} onSaved={() => void refresh(detail.data.import_id)} />}
      </section>
    )}
  </div>
}

function ImportStatus({ status }: { status: ImportJob['status'] }) {
  const labels: Record<ImportJob['status'], string> = {
    needs_structuring: '待结构化',
    queued: '已排队',
    preparing: '正在分析',
    ocr_queued: 'OCR 已排队',
    ocr_running: '正在本地 OCR',
    ready_for_review: '待页级审核',
    draft_building: '正在生成草稿',
    draft_ready: '审核草稿',
    ready_to_import: '可验证导入',
    imported: '已导入',
    failed: '处理失败',
  }
  return <StatusBadge tone={status === 'imported' ? 'success' : status === 'failed' ? 'warning' : 'neutral'}>{labels[status]}</StatusBadge>
}

function ImportDetailPanel({ job, ocrRuntime, onSaved }: { job: ImportJob; ocrRuntime?: OcrRuntime; onSaved: () => void }) {
  const pageDocuments = useMemo(
    () => (job.summary?.documents ?? []).filter((item) => ['pdf', 'image', 'text', 'document'].includes(item.file_kind)),
    [job.summary?.documents],
  )
  const audios = useMemo(
    () => (job.summary?.documents ?? []).filter((item) => item.file_kind === 'audio'),
    [job.summary?.documents],
  )
  const [storedName, setStoredName] = useState(pageDocuments[0]?.stored_name ?? '')
  const [pageNumber, setPageNumber] = useState(1)
  const [pagePlan, setPagePlan] = useState<Record<string, PageRole>>({})
  const document = pageDocuments.find((item) => item.stored_name === storedName) ?? pageDocuments[0]
  const pages = document?.pages ?? []
  const selectedPage = pages.find((item) => item.page_number === pageNumber) ?? pages[0]
  useEffect(() => {
    if (!pageDocuments.some((item) => item.stored_name === storedName)) {
      setStoredName(pageDocuments[0]?.stored_name ?? '')
    }
  }, [pageDocuments, storedName])
  useEffect(() => {
    setPagePlan(job.summary?.page_plan?.[storedName] ?? {})
    setPageNumber(1)
  }, [job.import_id, job.updated_at, job.summary?.page_plan, storedName])
  const savePlan = useMutation({
    mutationFn: () => api<ImportJob>(`/api/v1/content/imports/${job.import_id}/page-plan`, {
      method: 'PATCH',
      body: JSON.stringify({ stored_name: storedName, pages: pagePlan }),
      headers: { 'Content-Type': 'application/json' },
    }),
    onSuccess: onSaved,
  })
  const runOcr = useMutation({
    mutationFn: (pageNumbers: number[]) => api<ImportJob>(`/api/v1/content/imports/${job.import_id}/ocr`, {
      method: 'POST',
      body: JSON.stringify({ stored_name: storedName, pages: pageNumbers }),
      headers: { 'Content-Type': 'application/json' },
    }),
    onSuccess: onSaved,
  })
  const buildDraft = useMutation({
    mutationFn: () => api<ImportJob>(`/api/v1/content/imports/${job.import_id}/review-draft`, { method: 'POST' }),
    onSuccess: onSaved,
  })
  const draft = useQuery({
    queryKey: ['content-review-draft', job.import_id, job.summary?.review_draft?.revision],
    queryFn: () => api<ReviewDraft>(`/api/v1/content/imports/${job.import_id}/review-draft`),
    enabled: job.status === 'draft_ready' && job.summary?.review_draft?.status === 'ready',
  })
  if (!pageDocuments.length && !audios.length) {
    return <div className="empty-state"><h3>当前材料没有可进行页级整理的文档</h3><p>请上传 PDF、截图、文本或 Word 文档。</p></div>
  }
  if (!pageDocuments.length) {
    return <>{audios.map((audio) => <AudioReviewPanel key={audio.stored_name} job={job} storedName={audio.stored_name} onSaved={onSaved} />)}</>
  }
  const contentUrl = `/api/v1/content/imports/${job.import_id}/files/${encodeURIComponent(storedName)}/content`
  const previewUrl = document?.file_kind === 'pdf'
    ? `${contentUrl}#page=${selectedPage?.page_number ?? 1}`
    : contentUrl
  const plannedOcrPages = pages
    .filter((page) => page.extraction_status === 'ocr_required')
    .filter((page) => {
      const role = pagePlan[String(page.page_number)] ?? 'unassigned'
      return !['unassigned', 'exclude', 'task_visual'].includes(role)
    })
    .map((page) => page.page_number)
    .slice(0, ocrRuntime?.max_pages_per_run ?? 50)
  const hasPlannedContent = Object.values(pagePlan).some((role) => !['unassigned', 'exclude'].includes(role))
  return (
    <>
      <div className="section-heading">
        <div><p className="eyebrow">Material page review</p><h2>{job.title}</h2><p>先标记材料用途，再进行文字识别、题目结构化和人工审核。</p></div>
        {pageDocuments.length > 1 && <label>材料文件<select value={storedName} onChange={(event) => setStoredName(event.target.value)}>{pageDocuments.map((item) => <option key={item.stored_name} value={item.stored_name}>{item.stored_name}</option>)}</select></label>}
      </div>
      <div className="pdf-review-layout">
        <aside className="pdf-page-index" aria-label="材料页面列表">
          {pages.map((page) => (
            <button key={page.page_number} className={page.page_number === selectedPage?.page_number ? 'active' : ''} onClick={() => setPageNumber(page.page_number)}>
              <span>第 {page.page_number} 页</span>
              <small>
                {page.extraction_status === 'text_available'
                  ? `${page.text_chars} 字符`
                  : page.extraction_status === 'ocr_available'
                    ? `OCR ${page.text_chars} 字符`
                    : page.extraction_status === 'ocr_required'
                      ? '需要 OCR'
                      : '提取失败'}
              </small>
              {page.text_preview && <em>{page.text_preview}</em>}
            </button>
          ))}
        </aside>
        <div className="pdf-preview-panel">
          {document?.file_kind === 'image'
            ? <img className="import-image-preview" key={storedName} src={previewUrl} alt={`${storedName} 预览`} />
            : document?.file_kind === 'document'
              ? (
                <div className="document-preview-fallback">
                  <strong>{storedName}</strong>
                  <p>{selectedPage?.text_preview || 'Word 文档文字已在本地提取，可继续标记用途并生成审核草稿。'}</p>
                  <a className="button secondary" href={contentUrl} target="_blank" rel="noreferrer">打开原文件</a>
                </div>
              )
              : <iframe key={`${storedName}-${selectedPage?.page_number ?? 1}`} src={previewUrl} title={`${storedName} 第 ${selectedPage?.page_number ?? 1} 页预览`} />}
          {selectedPage && (
            <div className="pdf-page-plan">
              <label>第 {selectedPage.page_number} 页用途
                <select
                  value={pagePlan[String(selectedPage.page_number)] ?? 'unassigned'}
                  onChange={(event) => setPagePlan((current) => ({ ...current, [String(selectedPage.page_number)]: event.target.value as PageRole }))}
                >
                  {Object.entries(PAGE_ROLE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              <button className="button primary" onClick={() => savePlan.mutate()} disabled={savePlan.isPending}>保存页面用途</button>
            </div>
          )}
          <div className="pdf-processing-actions">
            {selectedPage?.extraction_status === 'ocr_required' && (
              <button
                className="button secondary"
                disabled={!ocrRuntime?.available || runOcr.isPending || ['ocr_queued', 'ocr_running'].includes(job.status)}
                onClick={() => runOcr.mutate([selectedPage.page_number])}
              >
                OCR 当前页
              </button>
            )}
            {plannedOcrPages.length > 0 && (
              <button
                className="button secondary"
                disabled={!ocrRuntime?.available || runOcr.isPending || ['ocr_queued', 'ocr_running'].includes(job.status)}
                onClick={() => runOcr.mutate(plannedOcrPages)}
              >
                OCR 已分类页面（{plannedOcrPages.length}）
              </button>
            )}
            <button
              className="button primary"
              disabled={!hasPlannedContent || buildDraft.isPending || ['ocr_queued', 'ocr_running', 'draft_building'].includes(job.status)}
              onClick={() => buildDraft.mutate()}
            >
              生成审核草稿
            </button>
          </div>
          {!ocrRuntime?.available && pages.some((page) => page.extraction_status === 'ocr_required') && (
            <p className="muted">扫描页需要先在上方安装隔离的本地 OCR；普通文本页可以直接生成草稿。</p>
          )}
          {(savePlan.error || runOcr.error || buildDraft.error) && <ErrorState error={savePlan.error ?? runOcr.error ?? buildDraft.error} />}
        </div>
      </div>
      {job.status === 'draft_building' && <LoadingState label="正在生成本地审核草稿" />}
      {draft.error && <ErrorState error={draft.error} />}
      {draft.data && <ReviewDraftEditor draft={draft.data} onSaved={onSaved} />}
      {audios.map((audio) => <AudioReviewPanel key={audio.stored_name} job={job} storedName={audio.stored_name} onSaved={onSaved} />)}
    </>
  )
}

function ReviewDraftEditor({ draft, onSaved }: { draft: ReviewDraft; onSaved: () => void }) {
  return (
    <section className="review-draft-editor">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Local review draft</p>
          <h2>页角色转换结果</h2>
          <p>这些内容仍是本地草稿。逐段校正和确认后，也不会自动成为正式题目；后续还需生成结构化题目并通过题库审核。</p>
        </div>
        <StatusBadge tone="warning">不可直接导入</StatusBadge>
      </div>
      {Boolean(draft.review_issues?.length) && (
        <div className="review-issue-list" aria-label="材料审核问题">
          {draft.review_issues?.map((issue) => (
            <article className={`review-issue ${issue.severity}`} key={issue.issue_id}>
              <div>
                <strong>{issue.severity === 'blocker' ? '阻断项' : issue.severity === 'warning' ? '需复核' : '提示'}</strong>
                <span>{issue.code}</span>
              </div>
              <p>{issue.message}</p>
              <small>页码：{issue.page_numbers.join('、') || '未指定'}{issue.evidence ? ` · ${issue.evidence}` : ''}</small>
            </article>
          ))}
        </div>
      )}
      <div className="review-draft-segments">
        {draft.segments.map((segment) => (
          <ReviewDraftSegmentEditor
            key={`${segment.segment_id}-${draft.revision}`}
            draft={draft}
            segment={segment}
            onSaved={onSaved}
          />
        ))}
      </div>
    </section>
  )
}

function ReviewDraftSegmentEditor({ draft, segment, onSaved }: { draft: ReviewDraft; segment: ReviewDraftSegment; onSaved: () => void }) {
  const [text, setText] = useState(segment.text)
  const save = useMutation({
    mutationFn: (reviewStatus: ReviewDraftSegment['review_status']) => api<ReviewDraft>(
      `/api/v1/content/imports/${draft.import_id}/review-draft/segments/${encodeURIComponent(segment.segment_id)}`,
      {
        method: 'PATCH',
        body: JSON.stringify({
          text,
          review_status: reviewStatus,
          expected_revision: draft.revision,
        }),
        headers: { 'Content-Type': 'application/json' },
      },
    ),
    onSuccess: onSaved,
  })
  return (
    <article className="review-draft-segment">
      <div>
        <strong>{PAGE_ROLE_LABELS[segment.role]}</strong>
        <small>{segment.stored_name} · 第 {segment.page_start}{segment.page_end !== segment.page_start ? `–${segment.page_end}` : ''} 页</small>
      </div>
      {segment.role === 'task_visual'
        ? <p className="muted">视觉页保留原 PDF 引用；可填写图表标题或人工说明。</p>
        : null}
      <textarea aria-label={`${PAGE_ROLE_LABELS[segment.role]}草稿文本`} value={text} onChange={(event) => setText(event.target.value)} rows={10} />
      <div className="row-actions">
        <button className="button secondary" disabled={save.isPending} onClick={() => save.mutate('needs_review')}>保存修改</button>
        <button className="button primary" disabled={save.isPending || (!text.trim() && segment.role !== 'task_visual')} onClick={() => save.mutate('reviewed')}>确认本段</button>
        <button className="button ghost" disabled={save.isPending} onClick={() => save.mutate('excluded')}>排除此段</button>
      </div>
      {save.error && <ErrorState error={save.error} />}
    </article>
  )
}

function AudioReviewPanel({ job, storedName, onSaved }: { job: ImportJob; storedName: string; onSaved: () => void }) {
  const sourceUrl = `/api/v1/content/imports/${job.import_id}/files/${encodeURIComponent(storedName)}/content`
  const audioRef = useRef<HTMLAudioElement>(null)
  const review = useQuery({
    queryKey: ['content-audio-review', job.import_id, storedName],
    queryFn: () => api<AudioReview>(`/api/v1/content/imports/${job.import_id}/audio-review/${encodeURIComponent(storedName)}`),
  })
  const [transcript, setTranscript] = useState('')
  const [cues, setCues] = useState<AudioCue[]>([])
  const [duration, setDuration] = useState<number | null>(null)
  useEffect(() => {
    if (!review.data) return
    setTranscript(review.data.transcript)
    setCues(review.data.cues)
    setDuration(review.data.duration_seconds ?? null)
  }, [review.data])
  const save = useMutation({
    mutationFn: (reviewStatus: AudioReview['review_status']) => api<AudioReview>(
      `/api/v1/content/imports/${job.import_id}/audio-review`,
      {
        method: 'PUT',
        body: JSON.stringify({
          stored_name: storedName,
          transcript,
          cues,
          duration_seconds: duration,
          review_status: reviewStatus,
          expected_revision: review.data?.revision ?? 0,
        }),
        headers: { 'Content-Type': 'application/json' },
      },
    ),
    onSuccess: async () => {
      await review.refetch()
      onSaved()
    },
  })
  const addCue = () => {
    const start = Number((audioRef.current?.currentTime ?? 0).toFixed(3))
    const end = Number(Math.min(duration ?? start + 5, start + 5).toFixed(3))
    setCues((current) => [
      ...current,
      {
        cue_id: `cue-${String(current.length + 1).padStart(4, '0')}`,
        start_seconds: start,
        end_seconds: end,
        text: '',
      },
    ])
  }
  if (review.isPending) return <LoadingState label="正在读取音频审核稿" />
  if (review.error || !review.data) return <ErrorState error={review.error} />
  return (
    <section className="audio-review-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Audio transcript review</p>
          <h2>{review.data.original_name ?? storedName}</h2>
          <p>波形只在当前浏览器本地计算；Transcript 和时间戳保存到本地审核稿，不会自动成为正式 Listening 答案证据。</p>
        </div>
        <StatusBadge tone={review.data.review_status === 'reviewed' ? 'success' : 'warning'}>
          {review.data.review_status === 'reviewed' ? '已审核' : '待审核'}
        </StatusBadge>
      </div>
      <AudioWaveform sourceUrl={sourceUrl} />
      <audio
        ref={audioRef}
        controls
        preload="metadata"
        src={sourceUrl}
        onLoadedMetadata={(event) => setDuration(Number(event.currentTarget.duration.toFixed(3)))}
      />
      <label>完整 Transcript
        <textarea value={transcript} onChange={(event) => setTranscript(event.target.value)} rows={10} placeholder="粘贴或人工校正完整转写；不要把未经核对的自动转写标为已审核。" />
      </label>
      <div className="audio-cue-heading">
        <div><strong>时间戳审核</strong><small>{cues.length} 条 · {duration ? formatSeconds(duration) : '等待音频时长'}</small></div>
        <button className="button secondary" onClick={addCue}>按当前播放位置添加</button>
      </div>
      <div className="audio-cue-list">
        {cues.map((cue, index) => (
          <div className="audio-cue-row" key={cue.cue_id ?? index}>
            <label>开始<input type="number" min={0} step={0.1} value={cue.start_seconds} onChange={(event) => setCues((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, start_seconds: Number(event.target.value) } : item))} /></label>
            <label>结束<input type="number" min={0} step={0.1} value={cue.end_seconds} onChange={(event) => setCues((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, end_seconds: Number(event.target.value) } : item))} /></label>
            <label>文字<input value={cue.text} onChange={(event) => setCues((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, text: event.target.value } : item))} /></label>
            <button className="button ghost" onClick={() => setCues((current) => current.filter((_, itemIndex) => itemIndex !== index))}>删除</button>
          </div>
        ))}
        {!cues.length && <p className="muted">播放到对应位置后添加时间戳，或手工输入起止秒数。</p>}
      </div>
      <div className="row-actions">
        <button className="button secondary" disabled={save.isPending} onClick={() => save.mutate('needs_review')}>保存审核稿</button>
        <button className="button primary" disabled={save.isPending || !transcript.trim() || !cues.length || cues.some((cue) => !cue.text.trim())} onClick={() => save.mutate('reviewed')}>确认 Transcript 与时间戳</button>
      </div>
      {save.error && <ErrorState error={save.error} />}
    </section>
  )
}

function AudioWaveform({ sourceUrl }: { sourceUrl: string }) {
  const [peaks, setPeaks] = useState<number[]>([])
  const [error, setError] = useState<Error | null>(null)
  useEffect(() => {
    let cancelled = false
    const context = new AudioContext()
    void fetch(sourceUrl, { credentials: 'same-origin' })
      .then((response) => {
        if (!response.ok) throw new Error(`音频读取失败：${response.status}`)
        return response.arrayBuffer()
      })
      .then((buffer) => context.decodeAudioData(buffer))
      .then((audioBuffer) => {
        if (cancelled) return
        const samples = audioBuffer.getChannelData(0)
        const barCount = 160
        const blockSize = Math.max(1, Math.floor(samples.length / barCount))
        const next = Array.from({ length: barCount }, (_, index) => {
          let peak = 0
          const start = index * blockSize
          const end = Math.min(samples.length, start + blockSize)
          for (let sample = start; sample < end; sample += 1) {
            peak = Math.max(peak, Math.abs(samples[sample]))
          }
          return Math.max(0.04, peak)
        })
        setPeaks(next)
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason : new Error(String(reason)))
      })
      .finally(() => {
        if (context.state !== 'closed') void context.close()
      })
    return () => {
      cancelled = true
      if (context.state !== 'closed') void context.close()
    }
  }, [sourceUrl])
  if (error) return <p className="muted">当前浏览器无法生成波形，仍可使用原生播放器和时间戳编辑。</p>
  return (
    <div className="audio-waveform" aria-label="本地音频波形">
      {peaks.length
        ? peaks.map((peak, index) => <i key={index} style={{ height: `${Math.max(8, Math.round(peak * 100))}%` }} />)
        : <span>正在本地计算波形…</span>}
    </div>
  )
}

function formatSeconds(value: number) {
  const minutes = Math.floor(value / 60)
  const seconds = Math.floor(value % 60)
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let amount = value / 1024
  let unit = units[0]
  for (let index = 1; index < units.length && amount >= 1024; index += 1) {
    amount /= 1024
    unit = units[index]
  }
  return `${amount >= 10 ? amount.toFixed(0) : amount.toFixed(1)} ${unit}`
}

const PAGE_ROLE_LABELS: Record<PageRole, string> = {
  unassigned: '尚未分类',
  passage: '阅读原文',
  questions: '题目',
  reading_test: '整套阅读（3 篇 / 40 题）',
  reading_passage: '阅读原文',
  reading_questions: '阅读题目',
  writing_task_1: '写作 Task 1',
  writing_task_2: '写作 Task 2',
  answer_key_with_writing_task_1: '混合页：阅读答案 + Writing Task 1',
  writing_task_2_with_task_1_visual: '混合页：Task 1 图表 + Writing Task 2',
  speaking_test: '口语 Part 1–3',
  speaking_test_with_sample_answers: '混合页：口语题目 + 示范回答',
  answer_key: '答案与解析',
  task_visual: 'Task 1 图表或视觉材料',
  transcript: '听力 Transcript',
  instructions: '考试说明',
  exclude: '不导入',
}

function reviewLabel(status?: string) {
  return ({ approved: '已批准', stale: '审核已过期', changes_requested: '待修改', rejected: '已拒绝', unreviewed: '未审核' } as Record<string, string>)[status ?? 'unreviewed'] ?? status
}
