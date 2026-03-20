'use client'

import { Suspense, useState } from 'react'
import { Sidebar } from '@/components/Sidebar'
import { Transactions } from '@/components/Transactions'
import { Marketplace } from '@/components/Marketplace'
import { DataVault } from '@/components/DataVault'
import { ChatContainer } from '@/components/chat/ChatContainer'
import { useChatStore } from '@/store/chatStore'

export default function Home() {
  const [activeTab, setActiveTab] = useState('research')
  const reset = useChatStore((s) => s.reset)

  return (
    <div className="flex h-screen overflow-hidden bg-slate-950 text-slate-100">
      <Suspense fallback={null}>
        <Sidebar
          activeTab={activeTab}
          onTabChange={setActiveTab}
          onNewResearch={() => {
            reset()
            setActiveTab('research')
          }}
        />
      </Suspense>

      <main className="flex flex-1 flex-col overflow-y-auto">
        <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-6 py-8">
          <div className="relative flex flex-1 flex-col">
            <div className="absolute inset-0 rounded-[28px] bg-gradient-to-br from-sky-500/15 via-transparent to-purple-600/20 blur-2xl" />
            <div className="relative flex flex-1 flex-col overflow-hidden rounded-[28px] border border-white/20 bg-slate-900/75 p-6 shadow-[0_45px_90px_-50px_rgba(56,189,248,0.9)] backdrop-blur-xl">
              {activeTab === 'research' && <ChatContainer />}
              {activeTab === 'transactions' && <Transactions />}
              {activeTab === 'marketplace' && <Marketplace />}
              {activeTab === 'data-vault' && <DataVault />}
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
