import type { Pose, Replay } from './replay'

export interface CrowdMix { ambient: number; cheer: number; whistleAt?: number }
export interface ScoringMoment { time: number; points: number }

const clamp = (value: number) => Math.max(0, Math.min(1, value))

// The quiet bed is constant. Danger, pressure and scoring drive the louder
// layer independently, so the stadium never falls silent between plays.
export function crowdMix(replay: Replay, pose: Pose, events: ScoringMoment[], time: number): CrowdMix {
  const rules = replay.header.rules
  const x = pose.ball.position[0]
  const goalDistance = Math.min(Math.abs(x), Math.abs(rules.length - x))
  const danger = clamp((rules.arc_radius + 2 - goalDistance) / 40)
  const carrier = pose.players.find((player) => player.id === pose.ball.owner)
  const nearestOpponent = carrier
    ? Math.min(...pose.players.filter((player) => player.id[0] !== carrier.id[0])
      .map((player) => Math.hypot(carrier.pos[0] - player.pos[0], carrier.pos[1] - player.pos[1])))
    : Infinity
  const pressure = clamp((4.5 - nearestOpponent) / 4.5)
  const shot = pose.ball.state === 'flight' && pose.ball.flight?.kind === 'kick' && danger > 0.25 ? 1 : 0
  const closeFinish = replay.header.seconds - time < 35 &&
    Math.abs(pose.score.A - pose.score.B) <= 6 ? 0.13 : 0
  let scoreSwell = 0
  let whistleAt: number | undefined
  for (const event of events) {
    const elapsed = time - event.time
    if (elapsed >= 0 && elapsed < 12) {
      scoreSwell = Math.max(scoreSwell, (event.points >= 6 ? 0.82 : 0.36) * Math.exp(-elapsed / (event.points >= 6 ? 3.6 : 2.1)))
    }
    if (elapsed >= 0 && elapsed < 0.35) whistleAt = event.time
  }
  const decision = replay.frames?.[pose.index]
  if (whistleAt === undefined && decision && (decision.trigger === 'ball-up' || decision.trigger === 'throw-in') &&
    time >= decision.t && time - decision.t < 0.35 && !events.some((event) => Math.abs(event.time - decision.t) < 1)) {
    whistleAt = decision.t
  }
  return {
    ambient: 0.24,
    cheer: clamp(0.05 + danger * 0.23 + pressure * 0.15 + shot * 0.16 + closeFinish + scoreSwell),
    whistleAt,
  }
}

export interface CrowdAudio {
  start: () => Promise<void>
  setMix: (mix: CrowdMix) => void
  close: () => void
}

// Real match ambience under a separate crowd swell. Whistles are one-shot cues,
// keyed by score time so frequent mix updates don't replay them repeatedly.
export function createCrowdAudio(): CrowdAudio {
  const context = new AudioContext()
  let bed: AudioBufferSourceNode | null = null
  let excitement: AudioBufferSourceNode | null = null
  let whistle: AudioBuffer | null = null
  let lastWhistle: number | undefined
  let closed = false
  const bedFilter = context.createBiquadFilter()
  bedFilter.type = 'lowpass'
  bedFilter.frequency.value = 1800
  const cheerFilter = context.createBiquadFilter()
  cheerFilter.type = 'highpass'
  cheerFilter.frequency.value = 280
  const bedGain = context.createGain()
  const cheerGain = context.createGain()
  bedGain.gain.value = 0
  cheerGain.gain.value = 0
  const compressor = context.createDynamicsCompressor()
  compressor.threshold.value = -18
  compressor.ratio.value = 3
  bedFilter.connect(bedGain).connect(compressor)
  cheerFilter.connect(cheerGain).connect(compressor)
  compressor.connect(context.destination)

  const load = async (name: string) => {
    const response = await fetch(`${import.meta.env.BASE_URL}audio/${name}.wav`)
    if (!response.ok) throw new Error(`Could not load ${name} sound`)
    return context.decodeAudioData(await response.arrayBuffer())
  }

  return {
    start: async () => {
      await context.resume()
      const [stadium, applause, whistleSound] = await Promise.all([
        load('stadium-crowd'), load('applause'), load('referee-whistle'),
      ])
      if (closed) return
      whistle = whistleSound
      bed = context.createBufferSource()
      bed.buffer = stadium
      bed.loop = true
      bed.connect(bedFilter)
      excitement = context.createBufferSource()
      excitement.buffer = applause
      excitement.loop = true
      excitement.connect(cheerFilter)
      bed.start()
      excitement.start()
    },
    setMix: ({ ambient, cheer, whistleAt }) => {
      if (closed) return
      const now = context.currentTime
      bedGain.gain.setTargetAtTime(clamp(ambient) * 0.8, now, 0.24)
      cheerGain.gain.setTargetAtTime(clamp(cheer) * 0.42, now, 0.3)
      bedFilter.frequency.setTargetAtTime(1300 + cheer * 1800, now, 0.35)
      if (whistleAt !== undefined && whistleAt !== lastWhistle && whistle) {
        lastWhistle = whistleAt
        const cue = context.createBufferSource()
        const gain = context.createGain()
        cue.buffer = whistle
        gain.gain.value = 0.24
        cue.connect(gain).connect(compressor)
        cue.start()
        cue.onended = () => { cue.disconnect(); gain.disconnect() }
      }
    },
    close: () => {
      if (closed) return
      closed = true
      bed?.stop()
      excitement?.stop()
      void context.close()
    },
  }
}
