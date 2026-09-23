#!/usr/bin/env node
/** Send a prompt to a native, user-visible DSH Web Session. */
import { createHash, randomUUID } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import process from 'node:process'
import WebSocket from 'ws'

function options(argv) {
  const [command, ...rest] = argv
  if (!['create', 'send', 'status', 'collect'].includes(command)) {
    throw new Error('usage: bridge.mjs <create|send|status|collect> [--key value]')
  }
  const values = { command }
  for (let i = 0; i < rest.length; i += 2) {
    const flag = rest[i]
    const value = rest[i + 1]
    if (!flag?.startsWith('--') || value === undefined) throw new Error(`invalid argument ${flag ?? ''}`)
    values[flag.slice(2)] = value
  }
  return values
}

function required(values, key) {
  const value = values[key]
  if (typeof value !== 'string' || value.trim() === '') throw new Error(`--${key} is required`)
  return value
}

async function promptText(values) {
  if (values.prompt !== undefined && values['prompt-file'] !== undefined) {
    throw new Error('use --prompt or --prompt-file, not both')
  }
  const prompt = values['prompt-file'] === undefined
    ? required(values, 'prompt')
    : await readFile(values['prompt-file'], 'utf8')
  if (prompt.trim() === '') throw new Error('prompt must not be blank')
  return prompt
}

async function rememberRequest(values, sessionId, requestId, cwd, prompt) {
  const directory = resolve(values['state-dir'] ?? '.agent-call-state/dsh-web')
  await mkdir(directory, { recursive: true, mode: 0o700 })
  const file = join(directory, `${createHash('sha256').update(requestId).digest('hex')}.json`)
  const record = { sessionId, requestId, cwd, promptHash: createHash('sha256').update(prompt).digest('hex') }
  try {
    await writeFile(file, JSON.stringify(record), { flag: 'wx', mode: 0o600 })
  } catch (error) {
    if (error?.code !== 'EEXIST') throw error
    const existing = JSON.parse(await readFile(file, 'utf8'))
    if (JSON.stringify(existing) !== JSON.stringify(record)) {
      throw new Error('requestId was already used with a different session, cwd, or prompt')
    }
  }
}

async function launchUrl(values) {
  let raw = process.env.DSH_WEB_LAUNCH_URL
  if (values['launch-url-file'] !== undefined) {
    const log = await readFile(values['launch-url-file'], 'utf8')
    raw = [...log.matchAll(/dsh web: (http:\/\/127\.0\.0\.1:\d+\/\?token=[A-Za-z0-9_-]+)/g)].at(-1)?.[1]
  }
  if (!raw) throw new Error('provide DSH_WEB_LAUNCH_URL or --launch-url-file containing the current DSH Web startup line')
  const url = new URL(raw)
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.searchParams.has('token') || url.username || url.password) {
    throw new Error('DSH launch URL must be a token-bearing http://127.0.0.1 URL')
  }
  return url
}

async function authenticatedWeb(values) {
  const url = await launchUrl(values)
  const response = await fetch(url, { redirect: 'manual', signal: AbortSignal.timeout(10_000) })
  const cookie = response.headers.get('set-cookie')?.split(';', 1)[0]
  if (response.status !== 303 || !cookie) throw new Error(`DSH Web startup authentication failed (HTTP ${response.status}); use this process's current launch URL`)
  return { origin: url.origin, cookie }
}

async function rpc(auth, endpoint, request, argKey = 'request') {
  const response = await fetch(`${auth.origin}/api/${endpoint}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', cookie: auth.cookie },
    body: JSON.stringify({
      type: 'client-request',
      rpcId: `agent-call-${randomUUID()}`,
      method: endpoint,
      payload: { args: { [argKey]: request } },
    }),
    signal: AbortSignal.timeout(20_000),
  })
  if (!response.ok) throw new Error(`${endpoint} returned HTTP ${response.status}`)
  const body = await response.json()
  if (body?.result?.ok !== true) {
    const error = body?.result?.error
    throw new Error(`${endpoint}: ${error?.code ?? 'unknown'}: ${error?.message ?? 'unknown error'}`)
  }
  return body.result.value
}

async function currentCursor(auth, sessionId) {
  const streamId = `agent-call-${randomUUID()}`
  const url = `${auth.origin.replace(/^http:/, 'ws:')}/api/remote.mux`
  const socket = new WebSocket(url, { headers: { cookie: auth.cookie } })
  return await new Promise((resolveCursor, reject) => {
    const timer = setTimeout(() => finish(new Error('session/follow timed out')), 10_000)
    function finish(error, cursor) {
      clearTimeout(timer)
      socket.close()
      if (error) reject(error)
      else resolveCursor(cursor)
    }
    socket.on('error', error => finish(error))
    socket.on('open', () => socket.send(JSON.stringify({
      type: 'open', streamId, endpoint: 'session/follow',
      payload: { args: { request: { address: { kind: 'session', sessionId } } } },
    })))
    socket.on('message', data => {
      let frame
      try { frame = JSON.parse(data.toString('utf8')) } catch { return }
      if (frame.streamId !== streamId) return
      if (frame.type === 'error') return finish(new Error(`session/follow: ${JSON.stringify(frame.error)}`))
      if (frame.type === 'item' && frame.value?.type === 'snapshot' && Number.isSafeInteger(frame.value.cursor)) {
        finish(undefined, frame.value.cursor)
      }
    })
  })
}

async function history(auth, sessionId) {
  const throughSeq = await currentCursor(auth, sessionId)
  const page = await rpc(auth, 'session/page', {
    address: { kind: 'session', sessionId }, throughSeq, maxMessages: 200,
  })
  return page.records.filter(record => record.type === 'event').map(record => record.event)
}

async function inspect(auth, sessionId, requestId) {
  const listed = await rpc(auth, 'session/list', {}, '_request')
  const session = listed.items.find(item => item.sessionId === sessionId)
  if (!session) throw new Error(`session ${sessionId} is not visible in this DSH Web process`)
  const events = await history(auth, sessionId)
  const sentAt = events.findIndex(event => event.type === 'user/message' && event.data?.source?.rpcId === requestId)
  const suffix = sentAt < 0 ? [] : events.slice(sentAt + 1)
  const endAt = suffix.findIndex(event => event.type === 'turn/end')
  const ended = endAt < 0 ? undefined : suffix[endAt]
  const relevant = endAt < 0 ? suffix : suffix.slice(0, endAt + 1)
  const answer = relevant.filter(event => event.type === 'assistant/message')
    .flatMap(event => event.data?.message?.content ?? [])
    .filter(part => part?.type === 'text')
    .map(part => part.text)
    .join('\n')
  return {
    sessionId, requestId, viewUrl: `${auth.origin}/`,
    cwd: session.cwd, running: session.running,
    status: ended ? 'worker_finished' : sentAt < 0 ? 'not_observed' : 'in_progress',
    ...(ended ? { terminationReason: ended.data?.reason } : {}),
    ...(ended ? { response: answer } : {}),
  }
}

async function main() {
  const values = options(process.argv.slice(2))
  const auth = await authenticatedWeb(values)
  if (values.command === 'create') {
    const cwd = resolve(required(values, 'cwd'))
    const created = await rpc(auth, 'session/create', { cwd })
    return { status: 'created', sessionId: created.sessionId, cwd, viewUrl: `${auth.origin}/` }
  }
  const sessionId = required(values, 'session-id')
  if (values.command === 'send') {
    const requestId = required(values, 'request-id')
    const prompt = await promptText(values)
    const cwd = resolve(required(values, 'cwd'))
    const listed = await rpc(auth, 'session/list', {}, '_request')
    const session = listed.items.find(item => item.sessionId === sessionId)
    if (!session || typeof session.cwd !== 'string' || resolve(session.cwd) !== cwd) {
      throw new Error('DSH session not found or cwd does not match --cwd')
    }
    await rememberRequest(values, sessionId, requestId, cwd, prompt)
    const receipt = await rpc(auth, 'session/prompt', {
      requestId, sessionId, mode: 'queue', content: [{ type: 'text', text: prompt }],
    })
    return { status: receipt.accepted ? 'accepted' : 'unknown', requestId, sessionId, viewUrl: `${auth.origin}/` }
  }
  const requestId = required(values, 'request-id')
  if (values.command === 'status') return await inspect(auth, sessionId, requestId)
  const timeoutMs = Math.max(1000, Number(values['timeout-ms'] ?? 60_000))
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const state = await inspect(auth, sessionId, requestId)
    if (state.status === 'worker_finished') return state
    await new Promise(resolveWait => setTimeout(resolveWait, 1000))
  }
  return { ...(await inspect(auth, sessionId, requestId)), waitTimedOut: true }
}

try {
  console.log(JSON.stringify(await main()))
} catch (error) {
  const message = (error instanceof Error ? error.message : String(error)).replace(/([?&]token=)[^\s&]+/g, '$1<redacted>')
  console.error(JSON.stringify({ error: message }))
  process.exitCode = 1
}
