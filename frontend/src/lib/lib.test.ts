import { describe, expect, it } from 'vitest'
import { applyEvent } from '@/hooks/useAgentChat'
import type { ChatItem } from './types'
import { readSSE } from './api'
import { plainText } from './speech'
import { actorLabel, money, pct } from './utils'

describe('applyEvent (chat stream reducer)', () => {
  it('merges consecutive text deltas from the same agent and depth', () => {
    let items: ChatItem[] = []
    items = applyEvent(items, { type: 'text', agent: 'copilot', depth: 0, delta: 'Hel' })
    items = applyEvent(items, { type: 'text', agent: 'copilot', depth: 0, delta: 'lo' })
    items = applyEvent(items, { type: 'text', agent: 'procurement', depth: 1, delta: 'Hi' })
    expect(items).toEqual([
      { type: 'text', agent: 'copilot', depth: 0, text: 'Hello' },
      { type: 'text', agent: 'procurement', depth: 1, text: 'Hi' },
    ])
  })

  it('ignores control events and appends others', () => {
    const items = applyEvent([], { type: 'done', conversation_id: 'c', trace_id: 't', status: 'ok', usage: { input_tokens: 0, output_tokens: 0 } })
    expect(items).toEqual([])
    const call = { type: 'tool_call' as const, agent: 'copilot', depth: 0, id: '1', name: 'x', args: {} }
    expect(applyEvent([], call)).toEqual([call])
  })
})

describe('readSSE', () => {
  it('parses data frames split across chunks', async () => {
    const chunks = ['data: {"a":', '1}\r\n\r\n: ping\r\n\r\ndata: {"b":2}\n\n']
    const body = new ReadableStream({
      start(controller) {
        chunks.forEach((c) => controller.enqueue(new TextEncoder().encode(c)))
        controller.close()
      },
    })
    const out = []
    for await (const e of readSSE(new Response(body))) out.push(e)
    expect(out).toEqual([{ a: 1 }, { b: 2 }])
  })
})

describe('formatters', () => {
  it('formats money, percentages and actors', () => {
    expect(money(123456.5)).toBe('₹1,23,457')
    expect(money(9.5)).toBe('₹9.50')
    expect(pct(12.345)).toBe('12.3%')
    expect(actorLabel('agent:procurement~manager@x')).toEqual({ label: 'procurement', isAgent: true })
    expect(actorLabel('user:meera@x.dev')).toEqual({ label: 'meera', isAgent: false })
  })

  it('strips markdown for text-to-speech', () => {
    expect(plainText('### Title\n- **bold** item\n| a | b |')).toBe('Title bold item')
  })
})
