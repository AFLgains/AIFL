export type Vec2 = [number, number]

export interface Player {
  id: string
  role: string
  pos: Vec2
  vel: Vec2
  energy: number
}

export type ActionKind = 'kick' | 'handball' | 'catch' | 'gather' | 'contest' | 'tackle' | 'bump'
export interface ActionCue { kind: ActionKind; time: number; direction?: Vec2; airborne?: boolean; intensity?: number }
export type LocomotionKind = 'start' | 'stop' | 'sprint' | 'jog'
export interface LocomotionCue { kind: LocomotionKind; time: number }
export interface FlightSegment { releaseTime: number; origin: Vec2; duration: number }
export interface HiddenHandball { releaseTime: number; origin: Vec2; receiver: string; from: string }
export interface AnimatedPlayer extends Player {
  distance: number
  action: ActionCue | null
  transition?: LocomotionCue | null
  facing?: number
}

export interface Ball {
  state: 'held' | 'loose' | 'flight'
  position: Vec2
  velocity: Vec2
  owner: string | null
  flight?: { kind: string; from: string; lands_at: Vec2; lands_in_s: number; markable?: boolean }
}

export interface Snapshot {
  kind: 'decision'
  k: number
  t: number
  trigger: string
  state: {
    score: { A: number; B: number }
    ball: Ball
    team_A: Player[]
    team_B: Player[]
    recent_events?: { t: number; type: string; by?: string }[]
  }
}

export interface Replay {
  header: {
    seconds: number
    team_A: string
    team_B: string
    final_score: { A: number; B: number }
    rules: { length: number; width: number; goal_half_width: number; behind_half_width: number; centre_square: number; centre_circle_radius: number; arc_radius: number }
  }
  frames: Snapshot[]
  motion?: Map<string, number[]>
  cues?: Map<string, ActionCue[]>
  transitions?: Map<string, LocomotionCue[]>
  facing?: Map<string, number[]>
  flightSegments?: Map<number, FlightSegment>
  hiddenHandballs?: Map<number, HiddenHandball>
}

export interface Pose {
  time: number
  index: number
  trigger: string
  score: { A: number; B: number }
  players: AnimatedPlayer[]
  ball: Ball & { height: number; flightElapsed?: number }
}

const mix = (a: number, b: number, t: number) => a + (b - a) * t
const mix2 = (a: Vec2, b: Vec2, t: number): Vec2 => [mix(a[0], b[0], t), mix(a[1], b[1], t)]
const separation = (a: Vec2, b: Vec2) => Math.hypot(a[0] - b[0], a[1] - b[1])

function flightPoint(origin: Vec2, destination: Vec2, kind: string, elapsed: number, duration: number, hidden = false) {
  const progress = Math.max(0, Math.min(1, elapsed / duration))
  return {
    position: mix2(origin, destination, progress),
    height: hidden ? 1.45 + 2.4 * Math.sin(Math.PI * progress) :
      0.28 + (kind === 'handball' ? 1.12 : 0.38) * (1 - progress) +
      Math.sin(Math.PI * progress) * (kind === 'handball' ? 2.4 : Math.min(12, 4 + duration * 2.2)),
  }
}

function sameFlight(a: Ball, b: Ball): boolean {
  return a.state === 'flight' && b.state === 'flight' && a.flight?.from === b.flight?.from &&
    a.flight?.kind === b.flight?.kind &&
    a.flight?.lands_at[0] === b.flight?.lands_at[0] && a.flight?.lands_at[1] === b.flight?.lands_at[1]
}

function addCue(cues: Map<string, ActionCue[]>, id: string, cue: ActionCue) {
  const entries = cues.get(id) ?? []
  entries.push(cue)
  cues.set(id, entries)
}

export function prepareReplay(replay: Replay): Replay {
  const motion = new Map<string, number[]>()
  const cues = new Map<string, ActionCue[]>()
  const transitions = new Map<string, LocomotionCue[]>()
  const facing = new Map<string, number[]>()
  const lastContact = new Map<string, number>()
  const flightSegments = new Map<number, FlightSegment>()
  const hiddenHandballs = new Map<number, HiddenHandball>()
  replay.frames.forEach((frame, index) => {
    const previous = replay.frames[index - 1]
    const prevPlayers = new Map(previous ? [...previous.state.team_A, ...previous.state.team_B].map((p) => [p.id, p]) : [])
    for (const player of [...frame.state.team_A, ...frame.state.team_B]) {
      const track = motion.get(player.id) ?? []
      const before = prevPlayers.get(player.id)
      const delta = before ? separation(before.pos, player.pos) : 0
      const dt = previous ? frame.t - previous.t : 0
      // A post-goal centre reset is a cut, not distance travelled on foot.
      const cut = frame.trigger === 'ball-up' && previous !== undefined &&
        (previous.state.score.A !== frame.state.score.A || previous.state.score.B !== frame.state.score.B)
      const jumped = cut || delta > 14 + dt * 10
      track.push((track.at(-1) ?? 0) + (jumped ? 0 : delta))
      motion.set(player.id, track)
      const headings = facing.get(player.id) ?? []
      const speed = Math.hypot(...player.vel)
      headings.push(speed > 0.65 ? Math.atan2(player.vel[1], player.vel[0]) : headings.at(-1) ?? (player.id[0] === 'A' ? 0 : Math.PI))
      facing.set(player.id, headings)
      if (before && !jumped && dt > 0) {
        const from = Math.hypot(...before.vel)
        for (const [threshold, goingUp, goingDown] of [[1.5, 'start', 'stop'], [5.5, 'sprint', 'jog']] as const) {
          if ((from < threshold && speed >= threshold) || (from >= threshold && speed < threshold)) {
            const entries = transitions.get(player.id) ?? []
            entries.push({ kind: speed >= threshold ? goingUp : goingDown, time: previous!.t + dt * (threshold - from) / (speed - from) })
            transitions.set(player.id, entries)
          }
        }
      }
    }
    const ball = frame.state.ball
    // A handball and catch can both occur between decisions, leaving two
    // consecutive "held" snapshots. Recover the flight from the event log.
    const oldBall = previous?.state.ball
    if (oldBall?.state === 'held' && oldBall.owner && ball.state === 'held' && ball.owner &&
      oldBall.owner !== ball.owner && previous && frame.t > previous.t) {
      const event = frame.state.recent_events?.find((entry) => entry.type === 'handball' && entry.by === oldBall.owner &&
        entry.t >= previous.t && entry.t < frame.t)
      const before = prevPlayers.get(oldBall.owner)
      const after = [...frame.state.team_A, ...frame.state.team_B].find((p) => p.id === oldBall.owner)
      if (event && before && after) {
        const fraction = Math.max(0, Math.min(1, (event.t - previous.t) / (frame.t - previous.t)))
        const origin = mix2(before.pos, after.pos, fraction)
        hiddenHandballs.set(index, { releaseTime: event.t, origin, from: oldBall.owner, receiver: ball.owner })
        addCue(cues, oldBall.owner, { kind: 'handball', time: event.t,
          direction: [ball.position[0] - origin[0], ball.position[1] - origin[1]] })
        addCue(cues, ball.owner, { kind: 'catch', time: frame.t,
          direction: [origin[0] - ball.position[0], origin[1] - ball.position[1]] })
      }
    }
    if (ball.state === 'flight' && ball.flight && (!previous || !sameFlight(previous.state.ball, ball))) {
      let releaseTime = frame.t
      let origin = ball.position
      let duration = ball.flight.lands_in_s
      if (ball.flight.kind === 'handball' && previous && frame.t > previous.t) {
        const shooterBefore = prevPlayers.get(ball.flight.from)
        const shooterNow = [...frame.state.team_A, ...frame.state.team_B].find((p) => p.id === ball.flight?.from)
        if (shooterBefore && shooterNow) {
          const dt = frame.t - previous.t
          const relativeVelocity: Vec2 = [
            ball.velocity[0] - (shooterNow.pos[0] - shooterBefore.pos[0]) / dt,
            ball.velocity[1] - (shooterNow.pos[1] - shooterBefore.pos[1]) / dt,
          ]
          const gap: Vec2 = [ball.position[0] - shooterNow.pos[0], ball.position[1] - shooterNow.pos[1]]
          const speedSquared = relativeVelocity[0] ** 2 + relativeVelocity[1] ** 2
          if (speedSquared > 1) {
            const elapsed = Math.max(0, Math.min(dt, (gap[0] * relativeVelocity[0] + gap[1] * relativeVelocity[1]) / speedSquared))
            releaseTime -= elapsed
            origin = [ball.position[0] - ball.velocity[0] * elapsed, ball.position[1] - ball.velocity[1] * elapsed]
            duration += elapsed
          }
        }
      }
      flightSegments.set(index, { releaseTime, origin, duration })
      addCue(cues, ball.flight.from, {
        kind: ball.flight.kind === 'handball' ? 'handball' : 'kick', time: releaseTime,
        direction: [ball.flight.lands_at[0] - origin[0], ball.flight.lands_at[1] - origin[1]],
      })
    }
    if (ball.state === 'held' && ball.owner && previous && !hiddenHandballs.has(index) &&
      (previous.state.ball.state !== 'held' || previous.state.ball.owner !== ball.owner) &&
      previous.state.score.A === frame.state.score.A && previous.state.score.B === frame.state.score.B) {
      const actor = prevPlayers.get(ball.owner)
      const wasInFlight = previous.state.ball.state === 'flight'
      addCue(cues, ball.owner, {
        kind: wasInFlight ? 'catch' : 'gather', time: frame.t,
        airborne: wasInFlight && frame.trigger !== 'kick-in' && previous.state.ball.flight?.kind === 'kick' && previous.state.ball.flight?.markable !== false,
        direction: actor ? [previous.state.ball.position[0] - actor.pos[0], previous.state.ball.position[1] - actor.pos[1]] : undefined,
      })
    }
    if (frame.trigger === 'spoil' && previous?.state.ball.state === 'flight') {
      for (const team of [frame.state.team_A, frame.state.team_B]) {
        const nearest = team.reduce<Player | null>((best, player) =>
          !best || separation(player.pos, ball.position) < separation(best.pos, ball.position) ? player : best, null)
        if (nearest && separation(nearest.pos, ball.position) < 4.5) {
          addCue(cues, nearest.id, {
            kind: 'contest', time: frame.t, airborne: true,
            direction: [ball.position[0] - nearest.pos[0], ball.position[1] - nearest.pos[1]],
          })
        }
      }
    }
    if (frame.trigger === 'tackle' && previous) {
      const formerOwner = previous.state.ball.owner
      const opponents = formerOwner
        ? (formerOwner[0] === 'A' ? frame.state.team_B : frame.state.team_A)
        : [...frame.state.team_A, ...frame.state.team_B]
      const defender = opponents.reduce<Player | null>((nearest, player) =>
        !nearest || separation(player.pos, ball.position) < separation(nearest.pos, ball.position) ? player : nearest, null)
      if (defender && separation(defender.pos, ball.position) < 3.5) {
        addCue(cues, defender.id, { kind: 'tackle', time: frame.t })
      }
    }
    // Sparse states do not log collisions. Solve for the closest point on each
    // pair of opposing movement segments and add a contact only on approach.
    if (previous && frame.t > previous.t && frame.trigger !== 'ball-up') {
      for (const a of frame.state.team_A) for (const b of frame.state.team_B) {
        const oldA = prevPlayers.get(a.id)
        const oldB = prevPlayers.get(b.id)
        if (!oldA || !oldB) continue
        const da: Vec2 = [a.pos[0] - oldA.pos[0], a.pos[1] - oldA.pos[1]]
        const db: Vec2 = [b.pos[0] - oldB.pos[0], b.pos[1] - oldB.pos[1]]
        const dt = frame.t - previous.t
        if (Math.hypot(...da) > 14 + dt * 10 || Math.hypot(...db) > 14 + dt * 10) continue
        const initial: Vec2 = [oldA.pos[0] - oldB.pos[0], oldA.pos[1] - oldB.pos[1]]
        const relative: Vec2 = [da[0] - db[0], da[1] - db[1]]
        const travelSq = relative[0] ** 2 + relative[1] ** 2
        const initialDistance = Math.hypot(...initial)
        if (initialDistance < 1.4 || travelSq < 0.25) continue
        const fraction = Math.max(0, Math.min(1, -(initial[0] * relative[0] + initial[1] * relative[1]) / travelSq))
        const nearest = Math.hypot(initial[0] + relative[0] * fraction, initial[1] + relative[1] * fraction)
        if (nearest > 1.2 || Math.sqrt(travelSq) / dt < 0.9) continue
        const contactTime = previous.t + fraction * dt
        const pair = `${a.id}:${b.id}`
        if (contactTime - (lastContact.get(pair) ?? -Infinity) < 0.85) continue
        lastContact.set(pair, contactTime)
        const intensity = Math.min(1, Math.max(0.35, Math.sqrt(travelSq) / dt / 6))
        addCue(cues, a.id, { kind: 'bump', time: contactTime, direction: [-initial[0], -initial[1]], intensity })
        addCue(cues, b.id, { kind: 'bump', time: contactTime, direction: initial, intensity })
      }
    }
  })
  return { ...replay, motion, cues, transitions, facing, flightSegments, hiddenHandballs }
}

function transitionAt(cues: LocomotionCue[] | undefined, time: number): LocomotionCue | null {
  if (!cues) return null
  let closest: LocomotionCue | null = null
  let distance = Infinity
  for (const cue of cues) {
    const difference = Math.abs(time - cue.time)
    if (time >= cue.time - 0.22 && time <= cue.time + 0.48 && difference < distance) {
      closest = cue
      distance = difference
    }
  }
  return closest
}

function actionAt(cues: ActionCue[] | undefined, time: number): ActionCue | null {
  if (!cues) return null
  let closest: ActionCue | null = null
  let distance = Infinity
  for (const cue of cues) {
    const lead = cue.kind === 'kick' ? 0.55 : cue.kind === 'handball' ? 0.46 :
      cue.kind === 'contest' ? 0.34 : cue.kind === 'gather' ? 0.26 : cue.kind === 'bump' ? 0.14 : 0.19
    const recovery = cue.kind === 'kick' ? 0.55 : cue.kind === 'handball' ? 0.65 :
      cue.kind === 'gather' || cue.kind === 'contest' ? 0.55 : 0.42
    if (time < cue.time - lead || time > cue.time + recovery) continue
    const difference = Math.abs(time - cue.time)
    if (closest?.kind !== 'bump' && cue.kind === 'bump' && closest) continue
    if (closest?.kind === 'bump' && cue.kind !== 'bump' || difference < distance) {
      closest = cue
      distance = difference
    }
  }
  return closest
}

export function parseReplay(text: string): Replay {
  const lines = text.trim().split(/\r?\n/).map((line) => JSON.parse(line) as Replay['header'] | Snapshot)
  const first = lines[0] as Replay['header'] & { kind?: string }
  if (first.kind !== 'header') throw new Error('Expected a JSONL replay header')
  const frames = lines.slice(1).filter((line): line is Snapshot => 'kind' in line && line.kind === 'decision')
  if (!frames.length) throw new Error('The replay contains no game states')
  return prepareReplay({ header: first, frames })
}

// Binary search keeps seeking cheap even for long matches. The snapshot timestamp (t),
// rather than rounded state.time, is the authoritative decision time.
export function frameAt(frames: Snapshot[], time: number): number {
  let low = 0
  let high = frames.length - 1
  while (low < high) {
    const mid = Math.ceil((low + high) / 2)
    if (frames[mid].t <= time) low = mid
    else high = mid - 1
  }
  return low
}

export function poseAt(replay: Replay, time: number): Pose {
  const frames = replay.frames
  const index = frameAt(frames, time)
  const current = frames[index]
  const next = frames[Math.min(index + 1, frames.length - 1)]
  const fraction = Math.max(0, Math.min(1, (time - current.t) / (next.t - current.t || 1)))
  const source = [...current.state.team_A, ...current.state.team_B]
  const destinations = new Map([...next.state.team_A, ...next.state.team_B].map((player) => [player.id, player]))
  // After a goal the engine resets the lineup at centre. Keep that reset instantaneous;
  // interpolating it would send every player flying through the stadium.
  const reset = next.trigger === 'ball-up' &&
    (next.state.score.A !== current.state.score.A || next.state.score.B !== current.state.score.B)
  const players = source.map((player) => {
    const destination = destinations.get(player.id) ?? player
    const distance = replay.motion?.get(player.id)?.[index] ?? 0
    return {
      ...player,
      pos: reset ? player.pos : mix2(player.pos, destination.pos, fraction),
      vel: reset ? player.vel : mix2(player.vel, destination.vel, fraction),
      energy: mix(player.energy, destination.energy, fraction),
      distance: distance + (reset ? 0 : separation(player.pos, destination.pos) * fraction),
      action: actionAt(replay.cues?.get(player.id), time),
      transition: reset ? null : transitionAt(replay.transitions?.get(player.id), time),
      facing: replay.facing?.get(player.id)?.[index],
    }
  })
  let ball = current.state.ball
  let upcomingFlight = false
  const hidden = replay.hiddenHandballs?.get(index + 1)
  if (hidden && time >= hidden.releaseTime && time < next.t) {
    const destination = next.state.ball.position
    const duration = next.t - hidden.releaseTime
    const { position, height } = flightPoint(hidden.origin, destination, 'handball', time - hidden.releaseTime, duration, true)
    return { time, index, trigger: current.trigger, score: current.state.score, players,
      ball: { state: 'flight', owner: null, position,
        velocity: [(destination[0] - hidden.origin[0]) / duration, (destination[1] - hidden.origin[1]) / duration],
        flight: { kind: 'handball', from: hidden.from, lands_at: next.state.ball.position, lands_in_s: duration },
        height, flightElapsed: time - hidden.releaseTime } }
  }
  if (ball.state !== 'flight' && next.state.ball.state === 'flight' &&
    next.state.ball.flight?.kind === 'handball') {
    const segment = replay.flightSegments?.get(index + 1)
    if (segment && time >= segment.releaseTime && time < next.t) {
      ball = next.state.ball
      upcomingFlight = true
    }
  }
  let position: Vec2 = ball.position
  let height = 0.22
  let flightElapsed: number | undefined
  if (ball.state === 'held' && ball.owner) {
    const owner = players.find((player) => player.id === ball.owner)
    if (owner) position = owner.pos
    height = 1.45
  } else if (ball.state === 'flight' && ball.flight) {
    let launch = upcomingFlight ? index + 1 : index
    while (!upcomingFlight && launch > 0) {
      const earlier = frames[launch - 1].state.ball
      if (!sameFlight(earlier, ball)) break
      launch--
    }
    const start = frames[launch]
    const origin = start.state.ball
    const segment = replay.flightSegments?.get(launch)
    const elapsed = Math.max(0, time - (segment?.releaseTime ?? start.t))
    flightElapsed = elapsed
    const duration = Math.max(0.1, segment?.duration ?? origin.flight!.lands_in_s)
    // Use the recorded horizontal flight and a presentation-only parabola.
    const point = flightPoint(segment?.origin ?? origin.position, ball.flight.lands_at, ball.flight.kind, elapsed, duration)
    position = point.position
    height = point.height
  } else if (!reset && next.state.ball.state === 'loose') {
    position = mix2(ball.position, next.state.ball.position, fraction)
  }
  return { time, index, trigger: current.trigger, score: current.state.score, players, ball: { ...ball, position, height, flightElapsed } }
}

// Sample the same interpolated 3D path used by the ball, starting no earlier
// than this release. A trail must never bridge two possessions or flights.
export function flightTrail(replay: Replay, pose: Pose): { time: number; position: Vec2; height: number }[] {
  if (pose.ball.state !== 'flight' || !pose.ball.flight || pose.ball.flightElapsed === undefined) return []
  const span = Math.min(pose.ball.flightElapsed, pose.ball.flight.kind === 'handball' ? 0.34 : 0.52)
  const steps = Math.min(6, Math.ceil(span / 0.07))
  if (!steps) return []
  const hidden = replay.hiddenHandballs?.get(pose.index + 1)
  const next = replay.frames[pose.index + 1]
  let origin: Vec2
  let destination: Vec2
  let duration: number
  if (hidden && next && pose.time >= hidden.releaseTime && pose.time < next.t) {
    origin = hidden.origin
    destination = next.state.ball.position
    duration = next.t - hidden.releaseTime
  } else {
    let launch = pose.index
    if (replay.frames[launch].state.ball.state !== 'flight') launch++ // inferred early handball release
    else while (launch > 0 && sameFlight(replay.frames[launch - 1].state.ball, pose.ball)) launch--
    const start = replay.frames[launch]
    const segment = replay.flightSegments?.get(launch)
    origin = segment?.origin ?? start.state.ball.position
    destination = pose.ball.flight.lands_at
    duration = Math.max(0.1, segment?.duration ?? start.state.ball.flight?.lands_in_s ?? 0.1)
  }
  return Array.from({ length: steps + 1 }, (_, i) => {
    const time = pose.time - span * (1 - i / steps)
    return { time, ...(i === steps ? { position: pose.ball.position, height: pose.ball.height } :
      flightPoint(origin, destination, pose.ball.flight!.kind, pose.ball.flightElapsed! - (pose.time - time), duration, Boolean(hidden && next && pose.time < next.t))) }
  })
}

export const clock = (seconds: number) => `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`

export function matchEvents(replay: Replay) {
  return replay.frames.filter((frame, index) => {
    const previous = replay.frames[index - 1]
    return previous && (frame.state.score.A !== previous.state.score.A || frame.state.score.B !== previous.state.score.B)
  }).map((frame) => {
    const previous = replay.frames[replay.frames.indexOf(frame) - 1]
    const team = frame.state.score.A !== previous.state.score.A ? 'A' : 'B'
    const points = frame.state.score[team] - previous.state.score[team]
    return { time: frame.t, team, label: points >= 6 ? 'Goal' : 'Behind', points }
  })
}
