import { convertToModelMessages, streamText } from 'ai'
import { openai } from '@ai-sdk/openai'

export const maxDuration = 60

interface DatasetContext {
  id: string
  title: string
  description?: string
  lab_name: string
  classification: string
  tags: string[]
  filename: string
  size_bytes: number
  content_type?: string
  verification_status: string
  proof_status: string
  reuse_count: number
  created_at?: string
}

function buildSystemPrompt(ctx: DatasetContext) {
  return `You are a data analysis assistant for the Synaptica Data Vault. You are helping a user understand a specific dataset.

## Dataset
- **Title**: ${ctx.title}
- **ID**: ${ctx.id}
- **Description**: ${ctx.description || '(none)'}
- **Lab**: ${ctx.lab_name}
- **Classification**: ${ctx.classification}
- **Tags**: ${ctx.tags?.join(', ') || 'none'}
- **File**: ${ctx.filename} (${ctx.content_type || 'unknown type'}, ${(ctx.size_bytes / 1024).toFixed(1)} KB)
- **Verification**: ${ctx.verification_status}
- **Proof**: ${ctx.proof_status}
- **Reuse count**: ${ctx.reuse_count}
- **Uploaded**: ${ctx.created_at || 'unknown'}

## Guidelines
- Answer questions about this dataset concisely.
- Explain what the dataset likely contains based on its metadata (title, description, tags, filename, classification).
- If asked about the actual data contents, note that you can see metadata but not the raw file — suggest the user preview it in the vault.
- Be helpful about potential reuse, quality assessment, and provenance.`
}

export async function POST(req: Request) {
  const { messages, datasetContext } = await req.json()
  const modelMessages = await convertToModelMessages(messages)

  const result = streamText({
    model: openai('gpt-4o'),
    system: buildSystemPrompt(datasetContext),
    messages: modelMessages,
  })

  return result.toUIMessageStreamResponse()
}
