import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronRight, Pause, Play, RotateCcw, Square } from 'lucide-react'

import ReplayScene from './ReplayScene'
import { poseAt, prepareReplay, type Replay, type Snapshot, type Vec2 } from './replay'
import './game.css'
import './game-overlay.css'

type Bot = { spec: string; kind: string }
type Session = { sid: string; human: 'A' | 'B'; names: Record<'A' | 'B', string>; seconds: number; rules: Replay['header']['rules'] }
type Tick = { frames: Snapshot[]; seq: number; ev: number; status: string; error?: string; control: { pid: string; next: string | null }; notes: [number, string, number, string][] }

export default function GameView() {
  const [bots, setBots] = useState<Bot[]>([])
  const [teamA, setTeamA] = useState('zoo:rules')
  const [teamB, setTeamB] = useState('zoo:zone')
  const [human, setHuman] = useState<'A' | 'B'>('A')
  const [seconds, setSeconds] = useState(240)
  const [session, setSession] = useState<Session | null>(null)
  const [replay, setReplay] = useState<Replay | null>(null)
  const [control, setControl] = useState('')
  const [note, setNote] = useState('')
  const [status, setStatus] = useState('setup')
  const [error, setError] = useState('')
  const [now, setNow] = useState(0)
  const keys = useRef(new Set<string>())
  const presses = useRef<string[]>([])
  const charge = useRef<number | null>(null)
  const seq = useRef(-1)
  const ev = useRef(0)
  const received = useRef(performance.now())
  const sessionRef = useRef<Session | null>(null)
  const busy = useRef(false)
  const paused = useRef(false)
  const pausePending = useRef(false)
  const cameraBasis = useRef<{ right: Vec2; forward: Vec2 }>({ right: [1, 0], forward: [0, 1] })

  useEffect(() => {
    fetch('/api/develop/bots').then((res) => res.ok ? res.json() : []).then((list: Bot[]) => setBots(list.filter((b) => b.kind !== 'llm'))).catch(() => setError('Could not load teams. Is the backend running?'))
  }, [])

  const stop = useCallback(() => {
    const old = sessionRef.current
    sessionRef.current = null
    if (old) void fetch(`/api/live/${old.sid}/stop`, { method: 'POST', keepalive: true })
    keys.current.clear()
    presses.current = []
    charge.current = null
    paused.current = false
    pausePending.current = false
    setSession(null)
    setStatus('setup')
  }, [])

  useEffect(() => () => {
    const old = sessionRef.current
    if (old) void fetch(`/api/live/${old.sid}/stop`, { method: 'POST', keepalive: true })
  }, [])

  async function start() {
    setError('')
    setStatus('starting')
    try {
      const response = await fetch('/api/live/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ opponent: human === 'A' ? teamB : teamA, helper: human === 'A' ? teamA : teamB, human, seconds, view: '3d' }) })
      if (!response.ok) throw new Error((await response.text()).slice(0, 300))
      const data: Session = await response.json()
      seq.current = -1
      ev.current = 0
      setReplay(null)
      setControl('')
      setNote('')
      paused.current = false
      pausePending.current = false
      sessionRef.current = data
      setSession(data)
      setStatus('playing')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not start the match')
      setStatus('setup')
    }
  }

  const togglePause = useCallback(async () => {
    const current = sessionRef.current
    if (!current || pausePending.current || paused.current !== (status === 'paused') || !['playing', 'paused'].includes(status)) return
    pausePending.current = true
    const next = !paused.current
    paused.current = next
    keys.current.clear()
    presses.current = []
    charge.current = null
    setStatus(next ? 'paused' : 'playing')
    try {
      const response = await fetch(`/api/live/${current.sid}/pause`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paused: next }) })
      if (!response.ok) throw new Error(`Could not ${next ? 'pause' : 'resume'} the match`)
      const result: { status: string } = await response.json()
      if (sessionRef.current === current && result.status !== (next ? 'paused' : 'playing')) {
        paused.current = result.status === 'paused'
        setStatus(result.status)
      }
    } catch (reason) {
      if (sessionRef.current !== current) return
      paused.current = !next
      setStatus(next ? 'playing' : 'paused')
      setError(reason instanceof Error ? reason.message : 'Could not change pause state')
    } finally { pausePending.current = false }
  }, [status])

  useEffect(() => {
    if (!session || !['playing', 'paused'].includes(status)) return
    const onDown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement && ['INPUT', 'SELECT', 'TEXTAREA'].includes(event.target.tagName)) return
      const key = event.key.toLowerCase()
      if (['arrowup', 'arrowdown', 'arrowleft', 'arrowright', ' ', 'p'].includes(key)) event.preventDefault()
      if (event.repeat) return
      if (key === 'p') { void togglePause(); return }
      if (key === 'escape') { stop(); return }
      if (status !== 'playing') return
      if (key === 'q') { presses.current.push('switch'); return }
      keys.current.add(key)
      if (key === ' ') {
        if (replay?.frames.at(-1)?.state.ball.owner === control) charge.current = performance.now()
        else presses.current.push('action')
      }
      if (key === 'j') presses.current.push('handball')
      if (key === 'l') presses.current.push('spoil')
    }
    const onUp = (event: KeyboardEvent) => {
      keys.current.delete(event.key.toLowerCase())
      if (event.key === ' ' && charge.current !== null) {
        presses.current.push(`kick:${Math.min(1.25, (performance.now() - charge.current) / 1000).toFixed(3)}`)
        charge.current = null
      }
    }
    const onBlur = () => { keys.current.clear(); charge.current = null }
    window.addEventListener('keydown', onDown)
    window.addEventListener('keyup', onUp)
    window.addEventListener('blur', onBlur)
    return () => { window.removeEventListener('keydown', onDown); window.removeEventListener('keyup', onUp); window.removeEventListener('blur', onBlur) }
  }, [session, status, replay, control, stop, togglePause])

  useEffect(() => {
    if (!session || !['playing', 'paused'].includes(status)) return
    let active = true
    const poll = async () => {
      if (busy.current || !active) return
      busy.current = true
      const held = keys.current
      const x = paused.current ? 0 : Number(held.has('arrowright') || held.has('d')) - Number(held.has('arrowleft') || held.has('a'))
      const y = paused.current ? 0 : Number(held.has('arrowup') || held.has('w')) - Number(held.has('arrowdown') || held.has('s'))
      const { right, forward } = cameraBasis.current
      const direction: Vec2 = [x * right[0] + y * forward[0], x * right[1] + y * forward[1]]
      const queued = paused.current ? [] : presses.current.splice(0)
      try {
        const response = await fetch(`/api/live/${session.sid}/tick`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ since: seq.current, ev: ev.current, input: { dir: direction, sprint: !paused.current && held.has('shift') }, presses: queued }) })
        if (!response.ok) throw new Error(`Live connection failed (${response.status})`)
        const data: Tick = await response.json()
        if (!active) return
        seq.current = data.seq
        ev.current = data.ev
        setControl(data.control.pid)
        if (data.notes.length) setNote(data.notes.at(-1)![1])
        if (data.frames.length) {
          received.current = performance.now()
          setReplay((previous) => prepareReplay({
            header: previous?.header ?? { seconds: session.seconds, team_A: session.names.A, team_B: session.names.B, final_score: { A: 0, B: 0 }, rules: session.rules },
            frames: [...(previous?.frames ?? []), ...data.frames].slice(-30),
          }))
        }
        if (data.status === 'playing' || data.status === 'paused') {
          if ((data.status === 'paused') === paused.current) setStatus(data.status)
        } else { setStatus(data.status); if (data.error) setError(data.error) }
      } catch (reason) {
        if (active) { presses.current.unshift(...queued); setError(reason instanceof Error ? reason.message : 'Connection lost') }
      } finally { busy.current = false }
    }
    void poll()
    const timer = window.setInterval(() => { void poll() }, 50)
    return () => { active = false; window.clearInterval(timer) }
  }, [session, status])

  useEffect(() => {
    if (!session || status === 'setup') return
    let frame = 0
    const animate = () => { setNow(performance.now()); frame = requestAnimationFrame(animate) }
    frame = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(frame)
  }, [session, status])

  const latest = replay?.frames.at(-1)
  const time = latest ? Math.min(latest.t, Math.max(replay!.frames[0].t, latest.t - 0.12 + (now - received.current) / 1000)) : 0
  const pose = replay && latest ? poseAt(replay, time) : null
  const label = (spec: string) => spec.replace('zoo:', '').replaceAll('_', ' ')
  const select = (value: string, change: (v: string) => void) => <select value={value} onChange={(event) => change(event.target.value)}>{bots.length ? bots.map((b) => <option value={b.spec} key={b.spec}>{label(b.spec)}</option>) : <option value={value}>{label(value)}</option>}</select>

  return <main className="game-main">
    {status === 'setup' || status === 'starting' ? <div className="game-setup">
      <div className="game-eyebrow">AFLHUB / GAME</div><h1>Take the field.</h1><p>Choose your teams and side. You control one player; your teammates and opponents play through the live sim engine.</p>
      <div className="game-setup-card"><div className="game-teams">
        <label>TEAM A <small>ATTACKS RIGHT</small>{select(teamA, setTeamA)}</label><span>VS</span><label>TEAM B <small>ATTACKS LEFT</small>{select(teamB, setTeamB)}</label>
      </div><div className="game-options"><label>PLAY AS <select value={human} onChange={(event) => setHuman(event.target.value as 'A' | 'B')}><option value="A">Team A</option><option value="B">Team B</option></select></label><label>MATCH LENGTH <select value={seconds} onChange={(event) => setSeconds(Number(event.target.value))}><option value={60}>1 minute</option><option value={120}>2 minutes</option><option value={240}>4 minutes</option></select></label></div>
      <button className="game-start" type="button" onClick={() => { void start() }} disabled={status === 'starting'}><Play size={18} fill="currentColor" /> {status === 'starting' ? 'STARTING…' : 'KICK OFF'} <ChevronRight size={18} /></button></div>
      {error && <p role="alert" className="game-error">{error}</p>}
      <div className="game-instructions">WASD / ARROWS move · SHIFT sprint · SPACE kick / contest · J handball · L spoil · Q switch</div>
    </div> : <div className="game-field">
      {pose && replay ? <ReplayScene replay={replay} pose={pose} view="broadcast" selected={control} onSelect={(pid) => { if (status === 'playing' && pid && pid[0] === session?.human) presses.current.push(`switch_to:${pid}`) }} onCameraBasis={(right, forward) => { cameraBasis.current = { right, forward } }} /> : <div className="game-wait">Preparing the oval…</div>}
      <div className="game-hud"><div className="game-score"><span>{session?.names.A}</span><strong>{pose?.score.A ?? 0} : {pose?.score.B ?? 0}</strong><span>{session?.names.B}</span></div><div className="game-clock">{Math.floor(time / 60)}:{String(Math.floor(time % 60)).padStart(2, '0')} / {session?.seconds && `${Math.floor(session.seconds / 60)}:00`}</div></div>
      <aside className="game-controls" aria-label="Game controls"><button type="button" className="game-pause" disabled={status !== 'playing' && status !== 'paused'} onClick={() => { void togglePause() }}>{status === 'paused' ? <Play size={16} fill="currentColor" /> : <Pause size={16} fill="currentColor" />}{status === 'paused' ? 'Resume' : 'Pause'} <kbd>P</kbd></button><div className="game-controls-list"><strong>CONTROLS</strong><span><kbd>↑ ↓ ← →</kbd> / <kbd>WASD</kbd> Move on screen</span><span><kbd>SHIFT</kbd> Sprint</span><span><kbd>SPACE</kbd> Kick / contest</span><span><kbd>J</kbd> Handball <kbd>L</kbd> Spoil</span><span><kbd>Q</kbd> Switch player</span><span><kbd>ESC</kbd> Exit game</span></div></aside>
      {status === 'paused' && <div className="game-paused">PAUSED <small>Press P or Resume to continue</small></div>}
      <div className="game-bottom"><div><strong>{status === 'playing' ? `YOU CONTROL ${control || '—'}` : status.toUpperCase()}</strong><small>{note || 'WASD move · SHIFT sprint · SPACE kick / contest · J handball · L spoil · Q switch'}</small>{error && <small className="game-error">{error}</small>}</div><div className="game-buttons">{status !== 'playing' && <button type="button" onClick={() => { stop(); void start() }}><RotateCcw size={16} /> Again</button>}<button type="button" onClick={stop}><Square size={14} /> Exit game</button></div></div>
    </div>}
  </main>
}
