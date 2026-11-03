import type { AuditEvent } from '../types'

async function hash(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export async function createMockAuditChain(events: Omit<AuditEvent, 'previousHash' | 'hash' | 'integrity'>[]): Promise<AuditEvent[]> {
  let previousHash = 'GENESIS'
  const chain: AuditEvent[] = []
  for (const event of events) {
    const currentHash = await hash(`${previousHash}:${event.id}:${event.type}:${event.timestamp}:${event.description}`)
    chain.push({ ...event, previousHash, hash: currentHash, integrity: 'Verified' })
    previousHash = currentHash
  }
  return chain
}

export async function verifyMockAuditChain(events: AuditEvent[]): Promise<boolean> {
  const rebuilt = await createMockAuditChain(events.map(({ id, type, timestamp, description }) => ({ id, type, timestamp, description })))
  return rebuilt.every((event, index) => event.hash === events[index]?.hash && event.previousHash === events[index]?.previousHash)
}
