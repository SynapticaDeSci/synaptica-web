import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'

// GET /api/credits?user_id=default  →  GET /api/credits/balance (FastAPI)
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url)
    const userId = searchParams.get('user_id') || 'default'

    const res = await fetch(`${BACKEND_URL}/api/credits/balance?user_id=${userId}`, {
      cache: 'no-store',
    })
    const data = await res.json()
    if (!res.ok) {
      return NextResponse.json({ error: data.detail || 'Failed to fetch balance' }, { status: res.status })
    }
    return NextResponse.json(data)
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}

// POST /api/credits  { credits, user_id }  →  POST /api/credits/checkout (FastAPI)
export async function POST(request: NextRequest) {
  try {
    const body = await request.json()

    const res = await fetch(`${BACKEND_URL}/api/credits/checkout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await res.json()
    if (!res.ok) {
      return NextResponse.json({ error: data.detail || 'Failed to create checkout' }, { status: res.status })
    }
    return NextResponse.json(data)
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
