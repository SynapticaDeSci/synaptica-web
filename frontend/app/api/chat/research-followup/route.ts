import { convertToModelMessages, streamText } from 'ai'
import { openai } from '@ai-sdk/openai'

export const maxDuration = 60

export async function POST(req: Request) {
  const { messages, researchContext } = await req.json()
  const modelMessages = await convertToModelMessages(messages)

  const citationBlock = Array.isArray(researchContext?.citations)
    ? researchContext.citations
        .map(
          (c: { citation_id?: string; title: string; url: string; publisher?: string }) =>
            `[${c.citation_id ?? ''}] ${c.title} — ${c.url}${c.publisher ? ` (${c.publisher})` : ''}`,
        )
        .join('\n')
    : ''

  const result = streamText({
    model: openai('gpt-4o'),
    system: `You are a research assistant. Answer follow-up questions about the research report below. Be concise and cite specific parts of the report when relevant.

## Research Report
${researchContext?.report ?? '(No report available)'}

## Cited Sources
${citationBlock || '(No citations available)'}`,
    messages: modelMessages,
  })

  return result.toUIMessageStreamResponse()
}
