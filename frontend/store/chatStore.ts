import { create } from 'zustand';

export type ChatPhase = 'chatting' | 'plan_ready' | 'executing' | 'complete';

export interface ResearchPlan {
  title: string;
  description: string;
  budget_estimate?: number;
  plan_steps: string[];
}

export interface ReportContext {
  report: string;
  citations: { citation_id?: string | null; title: string; url: string; publisher?: string | null }[];
}

interface ChatState {
  phase: ChatPhase;
  researchPlan: ResearchPlan | null;
  activeResearchRunId: string | null;
  reportContext: ReportContext | null;

  setPlan: (plan: ResearchPlan) => void;
  setActiveResearchRunId: (id: string) => void;
  setPhase: (phase: ChatPhase) => void;
  setComplete: (ctx: ReportContext) => void;
  reset: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  phase: 'chatting',
  researchPlan: null,
  activeResearchRunId: null,
  reportContext: null,

  setPlan: (plan) => set({ researchPlan: plan, phase: 'plan_ready' }),
  setActiveResearchRunId: (id) =>
    set({ activeResearchRunId: id, phase: 'executing' }),
  setPhase: (phase) => set({ phase }),
  setComplete: (ctx) => set({ phase: 'complete', reportContext: ctx }),
  reset: () =>
    set({
      phase: 'chatting',
      researchPlan: null,
      activeResearchRunId: null,
      reportContext: null,
    }),
}));
