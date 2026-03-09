# ProvidAI Frontend

Modern Next.js frontend for the ProvidAI AI Agent Marketplace, built with React, Zustand, and shadcn/ui.

## Features

- 📊 **State Management**: Zustand store for managing complex multi-step task workflow
- 🎨 **Modern UI**: Built with shadcn/ui components and Tailwind CSS
- 🔄 **BFF Pattern**: Next.js API routes act as Backend-for-Frontend proxy
- 🚀 **Real-time Updates**: Polling-based task status updates with execution logs
- ✅ **Task-Scoped Review Flow**: Human approval and rejection happen through the backend verification endpoints when a verifier requests review

## Tech Stack

- **Framework**: Next.js 14+ (App Router)
- **UI**: React 18, shadcn/ui, Tailwind CSS
- **State**: Zustand
- **Type Safety**: TypeScript

## Getting Started

### Prerequisites

- Node.js 18+ and npm/yarn
- Backend API running on `http://localhost:8000` (or configure `NEXT_PUBLIC_BACKEND_URL`)

### Installation

```bash
cd frontend
npm install
```

### Configuration

Create a `.env.local` file:

```env
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

### Development

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

### Building

```bash
npm run build
npm start
```

## Architecture

### State Management

The application uses Zustand for global state management. The `taskStore` manages:

- **Task Status**: IDLE → PLANNING → NEGOTIATING → EXECUTING → VERIFYING → COMPLETE/FAILED
- **Task Details**: Description, uploaded files, plan, selected agent
- **Execution**: Logs, progress, results
- **Verification**: Human review state when backend verification requires approval

### API Routes (BFF)

Next.js API routes act as a Backend-for-Frontend layer:

- `POST /api/tasks` - Create new task and start orchestration
- `GET /api/tasks/[taskId]` - Get task status

### Component Structure

```
app/
  layout.tsx          # Root layout with providers
  page.tsx            # Main application page
  providers.tsx       # React Query provider setup
  api/                # BFF API routes
    tasks/
      route.ts
      [taskId]/
        route.ts

components/
  ui/                 # shadcn/ui components
  TaskForm.tsx        # Task creation form
  TaskStatusCard.tsx  # Status display with progress
  TaskResults.tsx     # Results display

store/
  taskStore.ts        # Zustand state management

lib/
  api.ts              # API client functions
  utils.ts           # Utility functions
```

## User Flow

1. **Submit Task**: User enters task description and uploads file (optional)
2. **Planning**: Backend analyzes request and creates plan
3. **Negotiation**: Backend finds suitable agent from the marketplace
4. **Execution**: Agent executes task, real-time logs displayed
5. **Verification**: Verifier validates results; if needed, a human reviewer can approve or reject at the task level
6. **Complete**: Results displayed, user can rate agent

## Hedera Integration

- Payments use Hedera Testnet via backend-held credentials—no user wallet or signing flow is required.
- Frontend simply relays payment details to the backend once the user approves, keeping funds on the test network.
- Hedera network metadata is still surfaced in the UI (`HederaInfo` component) to highlight provenance.

## Development Notes

### Backend Integration

The frontend expects the backend to:

1. Return structured responses from `/execute` endpoint
2. Support task status polling via `/api/tasks/[taskId]`
3. Expose task-scoped review endpoints at `/api/tasks/[taskId]/approve_verification` and `/api/tasks/[taskId]/reject_verification`

### State Machine

The task workflow follows a strict state machine:

```
IDLE
  ↓ (user submits task)
PLANNING
NEGOTIATING
EXECUTING
  ↓ (execution complete)
VERIFYING
  ↓
COMPLETE / FAILED
```

### Error Handling

- Network errors are caught and displayed in the status card
- Verification review errors are surfaced through the verification card
- Task errors display in the results card

## Future Improvements

- [ ] WebSocket/SSE for real-time updates instead of polling
- [ ] File upload to IPFS or similar storage
- [ ] Enhanced agent selection UI with comparison
- [ ] Reputation visualization
- [ ] Payment history and receipts
- [ ] Task templates and saved configurations

## License

MIT
