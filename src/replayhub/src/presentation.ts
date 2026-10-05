import type { AnimatedPlayer, Vec2 } from './replay'

export interface Contact {
  intensity: number
  direction: Vec2 // From this player toward the nearest opponent, in field coordinates.
}

export interface StagedPlayer {
  player: AnimatedPlayer
  position: Vec2
  contact: Contact | null
}

const distance = (a: Vec2, b: Vec2) => Math.hypot(a[0] - b[0], a[1] - b[1])
const clamp = (v: number) => Math.max(0, Math.min(1, v))

function normal(a: Vec2, b: Vec2, i: number, j: number): Vec2 {
  const angle = ((i + 1) * 2.3999632 + (j + 1) * 1.618034) * 2.1
  const fallback: Vec2 = [Math.cos(angle), Math.sin(angle)]
  const separation = distance(a, b)
  if (separation < 0.01) return fallback
  // At the exact crossing point a displacement-derived normal would flip
  // instantly. Ease in a stable pair-specific direction instead.
  const t = clamp((separation - 0.08) / 0.6)
  const smooth = t * t * (3 - 2 * t)
  const x = fallback[0] * (1 - smooth) + (b[0] - a[0]) / separation * smooth
  const y = fallback[1] * (1 - smooth) + (b[1] - a[1]) / separation * smooth
  const length = Math.hypot(x, y)
  return length < 0.01 ? fallback : [x / length, y / length]
}

// This layer never changes game positions, outcomes, velocities or the replay.
// It makes coincident figures readable and supplies a soft ongoing contact pose.
export function stagePlayers(players: AnimatedPlayer[], owner: string | null): StagedPlayer[] {
  const staged = players.map((player): StagedPlayer => ({ player, position: [...player.pos], contact: null }))
  for (let pass = 0; pass < 7; pass++) {
    for (let i = 0; i < staged.length; i++) for (let j = i + 1; j < staged.length; j++) {
      const a = staged[i]
      const b = staged[j]
      const gap = distance(a.position, b.position)
      if (gap >= 1.08) continue
      const [nx, ny] = normal(a.player.pos, b.player.pos, i, j)
      const correction = 1.08 - gap
      const aShare = a.player.id === owner ? 0.15 : b.player.id === owner ? 0.85 : 0.5
      a.position[0] -= nx * correction * aShare
      a.position[1] -= ny * correction * aShare
      b.position[0] += nx * correction * (1 - aShare)
      b.position[1] += ny * correction * (1 - aShare)
    }
  }

  for (let i = 0; i < staged.length; i++) {
    const a = staged[i]
    let nearest: { opponent: StagedPlayer; index: number; gap: number } | null = null
    for (let j = 0; j < staged.length; j++) {
      const b = staged[j]
      if (a.player.id[0] === b.player.id[0]) continue
      const gap = distance(a.player.pos, b.player.pos)
      if (!nearest || gap < nearest.gap) nearest = { opponent: b, index: j, gap }
    }
    if (!nearest || nearest.gap >= 2.45) continue
    const { opponent, index, gap } = nearest
    const [nx, ny] = i < index
      ? normal(a.player.pos, opponent.player.pos, i, index)
      : normal(opponent.player.pos, a.player.pos, index, i).map((value) => -value) as Vec2
    const relativeSpeed = Math.hypot(a.player.vel[0] - opponent.player.vel[0], a.player.vel[1] - opponent.player.vel[1])
    const proximity = clamp((2.45 - gap) / 1.65)
    const intensity = proximity * (0.62 + 0.38 * clamp(relativeSpeed / 5))
    if (intensity > 0.02) a.contact = { intensity, direction: [nx, ny] }
  }
  return staged
}
