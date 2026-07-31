import { FileText, Image, Paperclip, Send, X } from 'lucide-react'
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react'

export function MaterialComposer({
  onSend,
  pending = false,
  disabled = false,
  placeholder = '和 IELTS 老师聊聊，或上传题目、原文和作文…',
  footer,
  autoFocus = false,
  compact = false,
}: {
  onSend: (content: string, files: File[]) => Promise<boolean | void>
  pending?: boolean
  disabled?: boolean
  placeholder?: string
  footer?: ReactNode
  autoFocus?: boolean
  compact?: boolean
}) {
  const inputId = useId()
  const fileInput = useRef<HTMLInputElement>(null)
  const textArea = useRef<HTMLTextAreaElement>(null)
  const [content, setContent] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const previews = useMemo(
    () => files.map((file) => ({
      file,
      url: file.type.startsWith('image/') ? URL.createObjectURL(file) : null,
    })),
    [files],
  )

  useEffect(
    () => () => previews.forEach((item) => item.url && URL.revokeObjectURL(item.url)),
    [previews],
  )

  async function submit(event: FormEvent) {
    event.preventDefault()
    const clean = content.trim()
    if (!clean || pending || disabled) return
    const sent = await onSend(clean, files)
    if (sent === false) return
    setContent('')
    setFiles([])
    if (textArea.current) textArea.current.style.height = ''
    if (fileInput.current) fileInput.current.value = ''
  }

  return (
    <form className={`material-composer${compact ? ' compact' : ''}`} onSubmit={submit}>
      <label className="sr-only" htmlFor={inputId}>向 IELTS 教师提问</label>
      <textarea
        ref={textArea}
        id={inputId}
        value={content}
        onChange={(event) => {
          setContent(event.target.value)
          if (compact) {
            event.currentTarget.style.height = 'auto'
            event.currentTarget.style.height = `${Math.min(event.currentTarget.scrollHeight, 144)}px`
          }
        }}
        placeholder={placeholder}
        autoFocus={autoFocus}
        rows={compact ? 1 : 3}
        title="Enter 发送，Shift+Enter 换行"
        onKeyDown={(event) => {
          if (
            event.key === 'Enter'
            && !event.shiftKey
            && !event.nativeEvent.isComposing
          ) {
            event.preventDefault()
            event.currentTarget.form?.requestSubmit()
          }
        }}
      />
      {previews.length > 0 && (
        <div className="composer-attachments" aria-label="待发送附件">
          {previews.map(({ file, url }, index) => (
            <div className="composer-attachment" key={`${file.name}-${file.lastModified}-${index}`}>
              {url
                ? <img src={url} alt="" />
                : <span>{file.type.startsWith('image/') ? <Image size={17} /> : <FileText size={17} />}</span>}
              <div><strong>{file.name}</strong><small>{formatBytes(file.size)}</small></div>
              <button
                type="button"
                aria-label={`移除 ${file.name}`}
                onClick={() => setFiles((current) => current.filter((_, itemIndex) => itemIndex !== index))}
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="composer-toolbar">
        <div className="composer-tools">
          <input
            ref={fileInput}
            type="file"
            multiple
            hidden
            accept=".png,.jpg,.jpeg,.webp,.pdf,.txt,.md,.docx"
            onChange={(event) => {
              const next = Array.from(event.target.files ?? [])
              setFiles((current) => [...current, ...next].slice(0, 8))
            }}
          />
          <button
            className="composer-tool"
            type="button"
            aria-label="添加材料"
            title="添加材料"
            onClick={() => fileInput.current?.click()}
            disabled={pending || disabled}
          >
            <Paperclip size={18} />
            <span>添加材料</span>
          </button>
          <small>图片、PDF、Word、TXT · 最多 8 个</small>
        </div>
        {footer}
        <button
          className="composer-send"
          type="submit"
          aria-label="发送给 IELTS 教师"
          disabled={!content.trim() || pending || disabled}
        >
          <Send size={18} />
        </button>
      </div>
    </form>
  )
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}
