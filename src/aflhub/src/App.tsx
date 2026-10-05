import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, ArrowRight, Camera, ChevronDown, ChevronLeft, ChevronRight, CircleHelp, Crosshair, Expand, Eye, FastForward, Focus, Maximize2, MoreHorizontal, Pause, Play, RotateCcw, SkipBack, SkipForward, Upload, Volume2, VolumeX } from 'lucide-react'

import ReplayScene from './ReplayScene'
import { createCrowdAudio, crowdMix } from './crowdAudio'
import type { CrowdAudio } from './crowdAudio'
import { clock, frameAt, matchEvents, parseReplay, poseAt } from './replay'
import type { Replay } from './replay'
import './index.css'
import './motion.css'

const GAME_LIBRARY = [
  { id: 'rounds', title: 'Round 36A vs Round 26A', subtitle: 'Exhibition match', file: 'example_game_states_round36a_v_round26a.jsonl' },
  { id: 'cup-final', title: 'Golden Shower Cup Final', subtitle: 'Golden Curry vs Power Tweaked', file: 'golden_shower_cup_final_29970.jsonl' },
] as const
type StoredGame = { id: string; title: string; subtitle: string }
const badge = (name: string) => name.split(' ').map((part) => part[0]).join('').slice(0, 2)
type View = 'broadcast' | 'free' | 'aerial' | 'onball'
const speeds = [0.5, 1, 1.5, 2]

function App() {
  const [replay, setReplay] = useState<Replay | null>(null)
  const [error, setError] = useState('')
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(1)
  const [view, setView] = useState<View>('broadcast')
  const [selected, setSelected] = useState<string | null>(null)
  const [showHelp, setShowHelp] = useState(false)
  const [showEvents, setShowEvents] = useState(true)
  const [selectedGame, setSelectedGame] = useState<string>(() => {
    const match = new URLSearchParams(window.location.search).get('match')
    return match && /^\d+$/.test(match) ? `match:${match}` : GAME_LIBRARY[0].id
  })
  const [storedGames, setStoredGames] = useState<StoredGame[]>([])
  const [fileName, setFileName] = useState<string>(GAME_LIBRARY[0].title)
  const [scrubbing, setScrubbing] = useState(false)
  const [crowdEnabled, setCrowdEnabled] = useState(false)
  const [audioError, setAudioError] = useState('')
  const crowdAudio = useRef<CrowdAudio | null>(null)
  const lastAudioTime = useRef(-Infinity)
  const fileInput = useRef<HTMLInputElement>(null)
  const stage = useRef<HTMLDivElement>(null)
  const lastTick = useRef(0)
  const games = [...GAME_LIBRARY, ...storedGames]

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/inspect/matches?scope=all&limit=50', { signal: controller.signal })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('Match library unavailable')))
      .then((data: { rows: { id: number; bot_a: string; bot_b: string; score_a: number; score_b: number }[] }) => {
        if (!controller.signal.aborted) setStoredGames(data.rows.map((row) => ({
          id: `match:${row.id}`, title: `${row.bot_a.split('/').at(-1)} vs ${row.bot_b.split('/').at(-1)}`,
          subtitle: `AIFL #${row.id} · ${row.score_a}–${row.score_b}`,
        })))
      }).catch(() => { /* Bundled JSONL matches also work without the backend. */ })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const game = GAME_LIBRARY.find((item) => item.id === selectedGame)
    const match = selectedGame.startsWith('match:') ? selectedGame.slice(6) : null
    if (!game && !match) return
    const controller = new AbortController()
    setReplay(null)
    setError('')
    setTime(0)
    setSelected(null)
    setSpeed(1)
    setView('broadcast')
    setPlaying(true)
    setFileName(game?.title ?? `AIFL match #${match}`)
    const url = match ? `/api/replayhub/matches/${match}/jsonl` : `${import.meta.env.BASE_URL}${game!.file}`
    fetch(url, { signal: controller.signal }).then((response) => {
      if (!response.ok) throw new Error(`Could not load ${game?.title ?? `match #${match}`} (${response.status})`)
      return response.text()
    }).then((text) => {
      if (!controller.signal.aborted) setReplay(parseReplay(text))
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Unable to load replay')
    })
    return () => controller.abort()
  }, [selectedGame])

  useEffect(() => {
    if (!playing || !replay || scrubbing) return
    let handle = 0
    lastTick.current = 0
    const update = (now: number) => {
      if (lastTick.current && now - lastTick.current >= 25) {
        const delta = Math.min(0.1, (now - lastTick.current) / 1000)
        setTime((previous) => Math.min(replay.header.seconds, previous + delta * speed))
        lastTick.current = now
      }
      if (!lastTick.current) lastTick.current = now
      handle = requestAnimationFrame(update)
    }
    handle = requestAnimationFrame(update)
    return () => cancelAnimationFrame(handle)
  }, [playing, replay, speed, scrubbing])

  useEffect(() => {
    if (replay && time >= replay.header.seconds) setPlaying(false)
  }, [replay, time])

  const seek = useCallback((value: number) => {
    setTime(Math.max(0, Math.min(replay?.header.seconds ?? 0, value)))
  }, [replay])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)) return
      if (event.code === 'Space') { event.preventDefault(); setPlaying((value) => !value) }
      if (event.code === 'ArrowLeft') { event.preventDefault(); seek(time - (event.shiftKey ? 5 : 1)) }
      if (event.code === 'ArrowRight') { event.preventDefault(); seek(time + (event.shiftKey ? 5 : 1)) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [seek, time])

  const pose = useMemo(() => replay ? poseAt(replay, time) : null, [replay, time])
  const events = useMemo(() => replay ? matchEvents(replay) : [], [replay])

  useEffect(() => {
    if (!crowdAudio.current || !crowdEnabled) return
    if (!playing || scrubbing || !replay || !pose) {
      crowdAudio.current.setMix({ ambient: 0, cheer: 0 })
      lastAudioTime.current = -Infinity
      return
    }
    if (Math.abs(time - lastAudioTime.current) < 0.1) return
    crowdAudio.current.setMix(crowdMix(replay, pose, events, time))
    lastAudioTime.current = time
  }, [crowdEnabled, events, playing, pose, replay, scrubbing, time])

  useEffect(() => () => crowdAudio.current?.close(), [])
  const handballs = useMemo(() => replay ? [...(replay.cues?.entries() ?? [])]
    .flatMap(([id, cues]) => cues.filter((cue) => cue.kind === 'handball').map((cue) => ({ id, time: cue.time })))
    .sort((a, b) => a.time - b.time) : [], [replay])
  const recentEvent = [...events].reverse().find((event) => event.time <= time)
  const activePlayer = pose?.players.find((player) => player.id === selected)
  const activeFrame = replay?.frames[frameAt(replay.frames, time)]
  const teamA = replay?.header.team_A.split('/').pop()?.replaceAll('_', ' ').toUpperCase() ?? 'ROUND 36A'
  const teamB = replay?.header.team_B.split('/').pop()?.replaceAll('_', ' ').toUpperCase() ?? 'ROUND 26A'

  function watchHandball() {
    const moment = handballs.find((cue) => cue.time > time + 0.7) ?? handballs[0]
    if (!moment) return
    seek(moment.time - 0.40)
    setSelected(moment.id)
    setView('broadcast')
    setSpeed(0.5)
    setPlaying(true)
  }

  async function toggleCrowd() {
    if (crowdAudio.current) {
      crowdAudio.current.close()
      crowdAudio.current = null
      setCrowdEnabled(false)
      return
    }
    try {
      const audio = createCrowdAudio()
      crowdAudio.current = audio
      await audio.start()
      if (crowdAudio.current !== audio) return
      lastAudioTime.current = -Infinity
      setCrowdEnabled(true)
      setAudioError('')
    } catch {
      crowdAudio.current?.close()
      crowdAudio.current = null
      setCrowdEnabled(false)
      setAudioError('Crowd sound could not start on this device.')
    }
  }

  async function importFile(file?: File) {
    if (!file) return
    try {
      const result = parseReplay(await file.text())
      setSelectedGame('custom')
      setReplay(result)
      setFileName(file.name.replace(/\.jsonl$/i, ''))
      setTime(0)
      setSelected(null)
      setSpeed(1)
      setView('broadcast')
      setPlaying(true)
      setError('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Invalid replay file')
    }
  }

  return <div className="shell">
    <aside className="rail">
      <div className="brand"><div className="brand-mark"><span>R</span></div><div><strong>REPLAY<span>ROOM</span></strong><small>THE GAME, REIMAGINED</small></div></div>
      <div className="rail-section-label">WORKSPACE</div>
      <button className="rail-item selected" type="button"><Activity size={18} /> Match replay <span className="rail-item-indicator" /></button>
      <button className="rail-item" type="button" onClick={() => fileInput.current?.click()}><Upload size={18} /> Import replay</button>
      <input ref={fileInput} type="file" accept=".jsonl,.txt" hidden onChange={(event) => { void importFile(event.target.files?.[0]); event.target.value = '' }} />
      <div className="rail-divider" />
      <div className="rail-section-label">MATCH LIBRARY</div>
      {games.map((game, index) => <button type="button" key={game.id} className={`library-game ${selectedGame === game.id ? 'active' : ''}`} onClick={() => setSelectedGame(game.id)} aria-pressed={selectedGame === game.id}>
        <span className="library-num">{String(index + 1).padStart(2, '0')}</span><span className="library-copy"><strong>{game.title}</strong><small>{game.subtitle}</small></span>
      </button>)}
      {selectedGame === 'custom' && <div className="library-game active"><span className="library-num">↗</span><span className="library-copy"><strong>{fileName}</strong><small>Imported replay</small></span></div>}
      <div className="rail-divider" />
      <div className="rail-section-label">NOW VIEWING</div>
      <div className="match-card">
        <div className="match-card-art"><span className="art-grid" /><span className="art-ball" /><span className="art-title">MATCH<br />DAY <em>{selectedGame === 'cup-final' ? '02' : '01'}</em></span></div>
        <div className="match-card-copy"><span className="status-dot" /> FULL MATCH REPLAY <strong>{teamA} <span>vs</span> {teamB}</strong><small>{replay?.frames[0]?.state.team_A.length ?? 8}-a-side · {clock(replay?.header.seconds ?? 240)} duration</small></div>
      </div>
      <div className="rail-grow" />
      <div className="rail-tip"><span className="tip-symbol">✦</span><strong>Get closer to the action</strong><p>Select a player on the field to follow their every move.</p><button type="button" onClick={() => setShowHelp(true)}>VIEW CONTROLS <ArrowRight size={14} /></button></div>
      <button className="rail-footer" type="button" onClick={() => setShowHelp(true)}><CircleHelp size={17} /> How to use <ChevronRight size={15} /></button>
    </aside>

    <main className="main">
      <header className="topbar"><div className="breadcrumbs">REPLAYS <ChevronRight size={13} /> <strong>{fileName.replaceAll('_', ' ')}</strong></div><div className="top-actions"><span className="live-indicator"><span /> INTERACTIVE REPLAY</span><button title="Import JSONL replay" type="button" onClick={() => fileInput.current?.click()}><Upload size={16} /> <span>Import JSONL</span></button><button className="icon-button" title="Help" type="button" onClick={() => setShowHelp(true)}><CircleHelp size={19} /></button></div></header>

      <div className="content">
        <div className="heading"><div><div className="eyebrow"><span className="eyebrow-line" /> MATCH CENTRE <span className="eyebrow-dot">·</span> SEASON REPLAY</div><h1>Every moment, <em>your perspective.</em></h1><p>Step onto the field. Relive every play from any angle.</p></div><div className="match-chip"><span className="chip-icon">✦</span><label htmlFor="game-select"><small>SELECT GAME</small><select id="game-select" aria-label="Select game to replay" value={selectedGame} onChange={(event) => setSelectedGame(event.target.value)}>{games.map((game) => <option key={game.id} value={game.id}>{game.title}</option>)}{selectedGame === 'custom' && <option value="custom">{fileName}</option>}{selectedGame.startsWith('match:') && !storedGames.some((game) => game.id === selectedGame) && <option value={selectedGame}>AIFL match #{selectedGame.slice(6)}</option>}</select></label><ChevronDown size={15} /></div></div>

        <section className="viewer" ref={stage} aria-label="Interactive 3D game replay">
          {replay && pose ? <ReplayScene replay={replay} pose={pose} view={view} selected={selected} onSelect={(id) => setSelected(id || null)} /> : <div className="loading"><span className="loading-ring" />{error || 'Preparing the stadium…'}</div>}
          <div className="viewer-vignette" />
          <div className="viewer-top"><div className="on-air"><span /> REPLAY <i /> CAM 01</div><div className="viewer-top-right"><span>THE OVAL <span className="viewer-top-sep">/</span> MATCHDAY</span><button type="button" title="Fullscreen" onClick={() => { if (!document.fullscreenElement) void stage.current?.requestFullscreen(); else void document.exitFullscreen() }}><Maximize2 size={17} /></button></div></div>
          <div className="scoreboard"><div className="score-team"><div className="team-logo logo-a">{badge(teamA)}</div><div className="team-info"><small>HOME</small><strong>{teamA}</strong></div></div><div className="score-values"><strong>{pose?.score.A ?? 0}</strong><span>:</span><strong>{pose?.score.B ?? 0}</strong></div><div className="score-team team-away"><div className="team-info"><small>AWAY</small><strong>{teamB}</strong></div><div className="team-logo logo-b">{badge(teamB)}</div></div><div className="score-time"><span className="clock-dot" /> {clock(time)} <small>/ {clock(replay?.header.seconds ?? 240)}</small></div></div>
          <div className="viewer-bottom"><div className="viewer-hint"><span>◉</span> {view === 'onball' ? 'ON BALL · DRAG TO ORBIT · SCROLL TO ZOOM' : selected ? `TRACKING ${selected}` : view === 'free' ? 'DRAG TO ROTATE · SCROLL TO ZOOM' : 'CLICK A PLAYER TO FOLLOW'}</div><div className="viewer-state"><span className="viewer-state-dot" /> {activePlayer ? `${activePlayer.id} · ${activePlayer.role.toUpperCase()}` : (activeFrame?.trigger ?? 'READY').toUpperCase()}</div></div>
          {recentEvent && time - recentEvent.time < 4 && <div className="goal-toast"><span>✦</span> {recentEvent.label.toUpperCase()} <strong>{recentEvent.team === 'A' ? teamA : teamB} +{recentEvent.points}</strong></div>}
        </section>

        <section className="transport" aria-label="Replay controls"><div className="transport-top"><div className="transport-title"><span className="transport-icon"><Play size={13} fill="currentColor" /></span><strong>MATCH TIMELINE</strong><span className="transport-count">{replay?.frames.length ?? '—'} MOMENTS</span><button type="button" className="highlight-jump" disabled={!handballs.length} onClick={watchHandball}>WATCH HANDBALL <ArrowRight size={12} /></button></div><div className="transport-keys">SPACE <span>PLAY / PAUSE</span> <i /> ← → <span>SEEK</span></div></div>
          <div className="timeline-wrap"><span className="timeline-time">{clock(time)}</span><div className="timeline-track"><div className="timeline-fill" style={{ width: `${100 * time / (replay?.header.seconds ?? 240)}%` }} />{events.map((event, index) => <button key={index} type="button" className={`timeline-marker ${event.team === 'A' ? 'a' : 'b'}`} title={`${clock(event.time)} · ${event.team} ${event.label}`} style={{ left: `${100 * event.time / (replay?.header.seconds ?? 240)}%` }} onClick={() => seek(event.time)} />)}<input type="range" min="0" max={replay?.header.seconds ?? 240} step="0.01" value={time} aria-label="Seek replay" onPointerDown={() => setScrubbing(true)} onPointerUp={() => setScrubbing(false)} onChange={(event) => seek(Number(event.target.value))} /></div><span className="timeline-time end">{clock(replay?.header.seconds ?? 240)}</span></div>
          <div className="transport-bottom"><div className="transport-left"><button className="tool-button" title="Restart" type="button" onClick={() => seek(0)}><RotateCcw size={16} /></button><span className="control-divider" /><button className="tool-button" title="Previous decision" type="button" onClick={() => replay && seek(replay.frames[Math.max(0, frameAt(replay.frames, time - 0.001))].t)}><SkipBack size={19} fill="currentColor" /></button><button className="tool-button" title="Back 5 seconds" type="button" onClick={() => seek(time - 5)}><ChevronLeft size={21} /></button><button className="play-button" title={playing ? 'Pause' : 'Play'} type="button" onClick={() => setPlaying(!playing)}>{playing ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" />}</button><button className="tool-button" title="Forward 5 seconds" type="button" onClick={() => seek(time + 5)}><ChevronRight size={21} /></button><button className="tool-button" title="Next decision" type="button" onClick={() => replay && seek(replay.frames[Math.min(replay.frames.length - 1, frameAt(replay.frames, time) + 1)].t)}><SkipForward size={19} fill="currentColor" /></button><span className="control-divider" /><button className="tool-button speed-button" title="Playback speed" type="button" onClick={() => setSpeed(speeds[(speeds.indexOf(speed) + 1) % speeds.length])}><FastForward size={16} /><span>{speed}×</span></button></div><div className="transport-right"><Volume2 size={17} className="muted-icon" /><span className="mute-note">VISUAL REPLAY</span><span className="control-divider" /><button type="button" onClick={() => setView('broadcast')} className={`camera-pill ${view === 'broadcast' ? 'active' : ''}`}><Camera size={15} /> Broadcast</button><button type="button" onClick={() => setView('free')} className={`camera-pill ${view === 'free' ? 'active' : ''}`}><Focus size={15} /> Free cam</button><button type="button" onClick={() => setView('aerial')} className={`camera-pill ${view === 'aerial' ? 'active' : ''}`}><Eye size={15} /> Aerial</button></div></div>
          <div className="onball-view"><button type="button" className={`crowd-toggle ${crowdEnabled ? 'active' : ''}`} aria-pressed={crowdEnabled} onClick={() => { void toggleCrowd() }} title={crowdEnabled ? 'Turn crowd sound off' : 'Turn crowd sound on'}>{crowdEnabled ? <Volume2 size={16} /> : <VolumeX size={16} />} CROWD SOUND {crowdEnabled ? 'ON' : 'OFF'}</button><button type="button" onClick={() => setView('onball')} className={`camera-pill ${view === 'onball' ? 'active' : ''}`} aria-pressed={view === 'onball'}><Crosshair size={16} /> On-ball camera <span>· drag to pivot around the ball</span></button></div>
          {audioError && <p className="crowd-audio-error" role="status">{audioError}</p>}
        </section>

        <div className="lower">
          <section className="activity-panel">
            <div className="panel-heading"><div><span className="section-icon"><Activity size={16} /></span><h2>Match moments</h2><span className="panel-count">{events.length}</span></div><button type="button" onClick={() => setShowEvents(!showEvents)}>{showEvents ? 'HIDE' : 'SHOW'} <ChevronDown size={15} className={showEvents ? '' : 'flipped'} /></button></div>
            {showEvents && <div className="event-list">{events.length ? events.map((event, index) => <button key={index} type="button" className={`event-row ${Math.abs(time - event.time) < 2 ? 'current' : ''}`} onClick={() => { seek(Math.max(0, event.time - 2)); setPlaying(true) }}><span className={`event-symbol ${event.team === 'A' ? 'orange' : 'blue'}`}>✦</span><div><strong>{event.label}</strong><small>{event.team === 'A' ? teamA : teamB} · +{event.points} points</small></div><time>{clock(event.time)}</time><ChevronRight size={16} /></button>) : <p className="empty-events">Loading match moments…</p>}</div>}
          </section>
          <aside className="info-panel">
            <div className="panel-heading"><div><span className="section-icon compass-icon"><Focus size={16} /></span><h2>On the field</h2></div><MoreHorizontal size={20} className="dots" /></div>
            <div className="focus-card"><div className="focus-glow">✦</div><small>{view === 'onball' ? 'BALL FOCUS' : selected ? 'PLAYER FOCUS' : 'CURRENT VIEW'}</small><strong>{view === 'onball' ? 'On-ball camera' : selected ? `${selected} · ${activePlayer?.role ?? 'Player'}` : view === 'broadcast' ? 'Broadcast camera' : view === 'free' ? 'Free camera' : 'Aerial camera'}</strong><p>{view === 'onball' ? 'The camera stays close to the ball. Drag to pivot around it and scroll to change distance.' : selected ? `Track ${selected} as the game unfolds. Click elsewhere on the field to release focus.` : view === 'free' ? 'Drag to orbit, right-drag to pan, and scroll to zoom in on the play.' : 'The camera follows the ball and keeps you close to the action.'}</p><span><span className="green-dot" /> {pose?.ball.state === 'held' ? `${pose.ball.owner} IN POSSESSION` : pose?.ball.state === 'flight' ? 'BALL IN FLIGHT' : 'LOOSE BALL'}</span></div>
            <div className="info-meta"><div>REPLAY ENGINE <strong>INTERACTIVE 3D</strong></div><div>FRAME <strong>{String((pose?.index ?? 0) + 1).padStart(3, '0')} / {replay?.frames.length ?? '---'}</strong></div></div>
          </aside>
        </div>
      </div>
    </main>
    {showHelp && <div className="modal-backdrop" onClick={() => setShowHelp(false)}><div className="help-modal" role="dialog" aria-modal="true" aria-label="Replay controls" onClick={(event) => event.stopPropagation()}><button className="modal-close" type="button" onClick={() => setShowHelp(false)}>×</button><span className="eyebrow">YOUR REPLAY, YOUR RULES</span><h2>Take the best seat<br /><em>in the house.</em></h2><p>Choose Broadcast to follow the play, Aerial for the full field, Free cam to explore, or On-ball to orbit the ball up close. Click a player to track them in Broadcast.</p><div className="help-row"><span>SPACE</span> Play or pause</div><div className="help-row"><span>← / →</span> Seek one second</div><div className="help-row"><span>SHIFT + ← / →</span> Seek five seconds</div><div className="help-row"><span>DRAG / SCROLL</span> Orbit and zoom in Free cam or On-ball</div><button className="help-cta" type="button" onClick={() => setShowHelp(false)}>BACK TO THE MATCH <ArrowRight size={17} /></button></div></div>}
    <div className="mobile-hint"><Expand size={15} /> Best experienced in landscape</div>
  </div>
}

export default App
