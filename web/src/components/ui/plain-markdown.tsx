import { Fragment, type ReactNode } from 'react'

/**
 * Простой Markdown из API (условия договора): абзацы, списки «- » и **жирный**.
 * Строки выводятся как текст — HTML из ответа не исполняется.
 */
export function PlainMarkdown({ source }: { source: string }) {
  const blocks: ReactNode[] = []
  let list: string[] = []
  const flush = () => {
    if (list.length === 0) return
    blocks.push(
      <ul key={`list-${blocks.length}`} className="grid list-disc gap-1 pl-5">
        {list.map((item, index) => (
          <li key={index}>{inline(item)}</li>
        ))}
      </ul>,
    )
    list = []
  }
  for (const line of source.split('\n')) {
    const trimmed = line.trim()
    if (/^[-*]\s+/.test(trimmed)) {
      list.push(trimmed.replace(/^[-*]\s+/, ''))
      continue
    }
    flush()
    if (trimmed) blocks.push(<p key={`p-${blocks.length}`}>{inline(trimmed)}</p>)
  }
  flush()
  return <div className="grid gap-3">{blocks}</div>
}

function inline(text: string): ReactNode {
  return text
    .split(/(\*\*[^*]+\*\*)/g)
    .map((part, index) =>
      part.startsWith('**') && part.endsWith('**') ? (
        <strong key={index}>{part.slice(2, -2)}</strong>
      ) : (
        <Fragment key={index}>{part}</Fragment>
      ),
    )
}
