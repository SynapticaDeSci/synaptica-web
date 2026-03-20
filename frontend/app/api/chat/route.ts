import { convertToModelMessages, streamText, tool } from 'ai';
import { openai } from '@ai-sdk/openai';
import { z } from 'zod';

export const maxDuration = 60;

const PLANNING_SYSTEM_PROMPT = `You are a research planning assistant for Synaptica, a decentralized science research platform.

Your job is to help users refine their research questions into actionable research plans. You should:

1. Understand the user's research question and intent.
2. Ask 1-2 concise clarifying questions about scope, desired depth, specific sub-topics, time period, or output format. Do NOT ask more than 2 rounds of questions — be efficient.
3. When you have enough context (usually after 1-2 exchanges), call the createResearchPlan tool with a structured plan.

Guidelines:
- Be concise and focused. Don't over-explain.
- If the query is already very specific and clear, you can create the plan immediately without asking questions.
- The plan should include clear investigation steps that map to the research question.
- The platform automatically detects the best research approach based on the query — you don't need to specify modes.
- Budget estimates should be reasonable: $5-20 for focused queries, $20-50 for broad multi-faceted research, $50-100 for comprehensive deep dives.`;

function buildFollowUpSystemPrompt(researchContext: {
  report?: string;
  citations?: { citation_id?: string; title: string; url: string; publisher?: string }[];
}) {
  const citationBlock = Array.isArray(researchContext.citations)
    ? researchContext.citations
        .map(
          (c) =>
            `[${c.citation_id ?? ''}] ${c.title} — ${c.url}${c.publisher ? ` (${c.publisher})` : ''}`,
        )
        .join('\n')
    : '';

  return `You are a research assistant. Answer follow-up questions about the research report below. Be concise and cite specific parts of the report when relevant.

## Research Report
${researchContext.report ?? '(No report available)'}

## Cited Sources
${citationBlock || '(No citations available)'}`;
}

const planningTools = {
  createResearchPlan: tool({
    description:
      'Create a structured research plan based on the conversation. Call this when you have enough context to define a clear research plan.',
    inputSchema: z.object({
      title: z
        .string()
        .describe('Short, descriptive title for the research run (max 80 chars)'),
      description: z
        .string()
        .describe(
          'Detailed research brief describing what to investigate, key questions to answer, and expected deliverables'
        ),
      budget_estimate: z
        .number()
        .describe('Estimated budget in USD'),
      plan_steps: z
        .array(z.string())
        .describe(
          'Ordered list of investigation steps the research will follow'
        ),
    }),
  }),
};

export async function POST(req: Request) {
  const { messages, researchContext } = await req.json();
  const modelMessages = await convertToModelMessages(messages);

  const isFollowUp = Boolean(researchContext?.report);

  const result = streamText({
    model: openai('gpt-4o'),
    system: isFollowUp
      ? buildFollowUpSystemPrompt(researchContext)
      : PLANNING_SYSTEM_PROMPT,
    messages: modelMessages,
    tools: isFollowUp ? undefined : planningTools,
  });

  return result.toUIMessageStreamResponse();
}
