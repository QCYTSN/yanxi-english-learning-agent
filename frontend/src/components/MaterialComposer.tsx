import { FileText, Image, Paperclip, Send, X } from 'lucide-react'
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ClipboardEvent as ReactClipboardEvent,
  type FormEvent,
  type ReactNode,
} from 'react'

const MAX_FILES = 8
const MAX_FILE_BYTES = 25 * 1024 * 1024
const MAX_MESSAGE_BYTES = 60 * 1024 * 1024

export function MaterialComposer({
  onSend,
  pending = false,
  disabled = false,
  placeholder = '和老师聊聊，或上传题目、原文和作文…',
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
  const [fileError, setFileError] = useState('')
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

  function appendFiles(nextFiles: File[]) {
    if (nextFiles.length === 0) return
    setFiles((current) => {
      const combined = [...current, ...nextFiles]
      if (combined.length > MAX_FILES) {
        setFileError(`每条消息最多添加 ${MAX_FILES} 个材料`)
        return current
      }
      const oversized = nextFiles.find((file) => file.size > MAX_FILE_BYTES)
      if (oversized) {
        setFileError(`${oversized.name} 超过 25 MB`)
        return current
      }
      const totalBytes = combined.reduce((total, file) => total + file.size, 0)
      if (totalBytes > MAX_MESSAGE_BYTES) {
        setFileError('本条消息的材料总大小不能超过 60 MB')
        return current
      }
      setFileError('')
      return combined
    })
  }

  function pasteImages(event: ReactClipboardEvent<HTMLTextAreaElement>) {
    const clipboardImages = Array.from(event.clipboardData.items)
      .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
      .map((item) => item.getAsFile())
      .filter((file): file is File => Boolean(file))
      .map(normaliseClipboardImage)
    if (clipboardImages.length === 0) return
    event.preventDefault()
    appendFiles(clipboardImages)
  }

  return (
    <form className={`material-composer${compact ? ' compact' : ''}`} onSubmit={submit}>
      <label className="sr-only" htmlFor={inputId}>向老师提问</label>
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
        onPaste={pasteImages}
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
      {fileError && <p className="composer-file-error" role="alert">{fileError}</p>}
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
              appendFiles(next)
              event.currentTarget.value = ''
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
          <small>可直接粘贴截图 · 最多 8 个</small>
        </div>
        {footer}
        <button
          className="composer-send"
          type="submit"
          aria-label="发送给老师"
          disabled={!content.trim() || pending || disabled}
        >
          <Send size={18} />
        </button>
      </div>
    </form>
  )
}

function normaliseClipboardImage(file: File) {
  if (file.name && !/^(image|clipboard)(\.\w+)?$/i.test(file.name)) return file
  const extension = ({
    'image/jpeg': 'jpg',
    'image/webp': 'webp',
  } as Record<string, string>)[file.type] ?? 'png'
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  return new File([file], `screenshot-${timestamp}.${extension}`, {
    type: file.type || `image/${extension}`,
    lastModified: file.lastModified || Date.now(),
  })
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}
