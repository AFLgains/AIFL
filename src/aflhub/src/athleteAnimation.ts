import type { AnimatedPlayer, LocomotionKind, Vec2 } from './replay'
import type { Contact } from './presentation'

export type Point3 = [number, number, number]
export type Expression = 'neutral' | 'jogging' | 'sprinting' | 'carrying' | 'handballing' | 'kicking' | 'catching' | 'gathering' | 'contesting' | 'tackling' | 'bumping' | 'jostling' | 'protecting'
export type Pace = 'idle' | 'jog' | 'sprint'

export interface Limb { hip: Point3; knee: Point3; foot: Point3; shoulder: Point3; elbow: Point3; hand: Point3 }
export interface AthleteAnimation {
  pace: Pace
  sprint: number
  transition: LocomotionKind | null
  heading: number
  bob: number
  jump: number
  leap: Vec2
  lean: number
  twist: number
  roll: number
  crouch: number
  limbs: [Limb, Limb]
  ball: Point3
  expression: Expression
}

const clamp = (value: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, value))
const smooth = (start: number, end: number, value: number) => {
  const t = clamp((value - start) / (end - start))
  return t * t * (3 - 2 * t)
}
const blend = (from: Point3, to: Point3, weight: number): Point3 => [
  from[0] + (to[0] - from[0]) * weight,
  from[1] + (to[1] - from[1]) * weight,
  from[2] + (to[2] - from[2]) * weight,
]

// Pure, distance-driven motion: pausing and seeking produce the same limb pose.
// Every full stride covers roughly 2.8m. No wall-clock or mutable animation mixer.
export function athleteAnimation(player: AnimatedPlayer, time: number, hasBall: boolean, contact: Contact | null = null): AthleteAnimation {
  const speed = Math.hypot(...player.vel)
  const gait = smooth(0.35, 2.6, speed)
  const sprint = smooth(4.6, 6.6, speed)
  const pace: Pace = speed >= 5.5 ? 'sprint' : speed >= 1.5 ? 'jog' : 'idle'
  const phase = player.distance * Math.PI * 2 / 2.8 + (Number(player.id.slice(1)) % 3) * 0.18
  const action = player.action
  const dt = action ? time - action.time : 0
  let heading = speed > 0.65 ? Math.atan2(player.vel[1], player.vel[0]) : player.facing ?? (player.id[0] === 'A' ? 0 : Math.PI)
  if (action?.direction && Math.hypot(...action.direction) > 0.25) {
    const direction: Vec2 = action.direction
    const aim = Math.atan2(direction[1], direction[0])
    const difference = Math.atan2(Math.sin(aim - heading), Math.cos(aim - heading))
    const turn = action.kind === 'kick' ? smooth(-0.55, -0.12, dt) * (1 - smooth(0.23, 0.55, dt)) :
      action.kind === 'handball' ? smooth(-0.46, -0.12, dt) * (1 - smooth(0.20, 0.52, dt)) * 0.85 :
        action.kind === 'bump' ? smooth(-0.14, 0, dt) * (1 - smooth(0.11, 0.42, dt)) * 0.24 :
          smooth(-0.28, -0.07, dt) * (1 - smooth(0.13, 0.48, dt)) * 0.75
    heading += difference * turn
  }
  let kick = 0
  let handball = 0
  let catchWeight = 0
  let gather = 0
  let contest = 0
  let tackle = 0
  let bump = 0
  if (action?.kind === 'kick') kick = smooth(-0.32, -0.12, dt) * (1 - smooth(0.25, 0.55, dt))
  if (action?.kind === 'handball') handball = smooth(-0.45, -0.31, dt) * (1 - smooth(0.31, 0.64, dt))
  if (action?.kind === 'catch') catchWeight = smooth(-0.19, -0.04, dt) * (1 - smooth(0.07, 0.41, dt))
  if (action?.kind === 'gather') gather = smooth(-0.26, -0.07, dt) * (1 - smooth(0.10, 0.54, dt))
  if (action?.kind === 'contest') contest = smooth(-0.32, -0.11, dt) * (1 - smooth(0.13, 0.50, dt))
  if (action?.kind === 'tackle') tackle = smooth(-0.19, -0.02, dt) * (1 - smooth(0.12, 0.42, dt))
  if (action?.kind === 'bump') bump = smooth(-0.14, 0.015, dt) * (1 - smooth(0.15, 0.48, dt)) * (action.intensity ?? 1)
  const jostle = (contact?.intensity ?? 0) * (1 - Math.min(1, (kick + handball + catchWeight + gather + contest + tackle + bump) * 0.96))
  const contactSide = contact && Math.cos(heading) * contact.direction[1] - Math.sin(heading) * contact.direction[0] >= 0 ? 1 : -1
  const contactPulse = Math.sin(time * 5.4 + Number(player.id.slice(1)) * 1.8)

  const jump = action?.airborne && (action.kind === 'catch' || action.kind === 'contest')
    ? Math.sin(Math.PI * clamp((dt + 0.28) / 0.56)) * (action.kind === 'contest' ? 0.78 : 0.72) : 0
  const incoming = action?.kind === 'catch' && action.airborne ? action.direction : undefined
  const incomingLength = incoming ? Math.hypot(...incoming) : 0
  const leapAmount = incomingLength > 0.01 ? Math.min(0.85, incomingLength * 0.22) *
    Math.sin(Math.PI * clamp((dt + 0.28) / 0.56)) : 0
  const leap: Vec2 = incoming && incomingLength > 0.01
    ? [incoming[0] / incomingLength * leapAmount, incoming[1] / incomingLength * leapAmount] : [0, 0]

  const transition = player.transition
  const transitionTime = transition ? time - transition.time : 0
  const transitionWeight = transition
    ? smooth(-0.22, -0.03, transitionTime) * (1 - smooth(0.18, 0.48, transitionTime)) : 0
  const launch = transition?.kind === 'start' ? transitionWeight : 0
  const burst = transition?.kind === 'sprint' ? transitionWeight : 0
  const brake = transition?.kind === 'jog' || transition?.kind === 'stop' ? transitionWeight : 0
  const bob = (1 - Math.min(1, jump)) * gait * (0.028 + (0.025 + 0.033 * sprint) * Math.cos(phase * 2)) +
    Math.sin(time * 2.2 + Number(player.id.slice(1))) * 0.009 * (1 - gait) + 0.026 * jostle * contactPulse
  const crouch = 0.24 * tackle + 0.09 * catchWeight + 0.38 * gather + 0.12 * contest +
    0.11 * bump + 0.08 * jostle + 0.12 * launch + 0.06 * burst
  const lean = -0.05 * gait - 0.19 * sprint - 0.12 * launch - 0.12 * burst +
    0.17 * brake - 0.13 * tackle + 0.13 * catchWeight + 0.10 * kick -
    0.62 * gather + 0.18 * contest + 0.24 * bump + jostle * (0.09 + contactPulse * 0.045)
  // The fist meets the ball at the inferred release, then completes its follow-through.
  const punch = action?.kind === 'handball' ? smooth(-0.18, 0.07, dt) : 0
  const twist = handball * (0.20 - punch * 0.36) + bump * (player.id[0] === 'A' ? 0.23 : -0.23) + contactSide * jostle * (0.12 + 0.06 * contactPulse)
  const roll = bump * (player.id[0] === 'A' ? -0.14 : 0.14) + contactSide * jostle * contactPulse * 0.06
  const limbs = ([-1, 1] as const).map((side): Limb => {
    const swing = Math.sin(phase + (side === 1 ? 0 : Math.PI))
    const lift = Math.max(0, Math.cos(phase + (side === 1 ? 0 : Math.PI)))
    const foot: Point3 = [gait * swing * (0.43 + 0.40 * sprint), 0.24 - bob + gait * lift * (0.22 + 0.33 * sprint), side * (0.23 + 0.03 * sprint)]
    const hip: Point3 = [0, 1.04 - crouch, side * 0.22]
    const knee: Point3 = [(hip[0] + foot[0]) * 0.5 + 0.16 + gait * lift * (0.13 + 0.28 * sprint), (hip[1] + foot[1]) * 0.51, side * 0.23]
    const shoulder: Point3 = [0, 1.76 - crouch, side * 0.37]
    const elbow: Point3 = [-swing * gait * (0.14 + 0.20 * sprint) + 0.1, 1.48 - crouch + 0.12 * sprint, side * (0.43 + 0.06 * sprint)]
    const hand: Point3 = [-swing * gait * (0.27 + 0.38 * sprint) + 0.04, 1.27 - crouch + 0.17 * sprint + Math.max(0, swing) * gait * (0.06 + 0.09 * sprint), side * 0.39]
    const limb = { hip, knee, foot, shoulder, elbow, hand }

    if (launch || burst) {
      const weight = Math.max(launch, burst)
      limb.foot = blend(limb.foot, side === 1 ? [0.49, 0.30, 0.24] : [-0.47, 0.24, -0.27], weight)
      limb.knee = blend(limb.knee, side === 1 ? [0.39, 0.72, 0.23] : [0.03, 0.51, -0.24], weight)
      limb.elbow = blend(limb.elbow, [-0.08, 1.59 - crouch, side * 0.43], weight)
      limb.hand = blend(limb.hand, [side === 1 ? -0.26 : 0.47, 1.44 - crouch, side * 0.42], weight)
    }
    if (brake) {
      limb.foot = blend(limb.foot, side === 1 ? [0.57, 0.25, 0.24] : [-0.34, 0.24, -0.26], brake)
      limb.knee = blend(limb.knee, side === 1 ? [0.45, 0.69, 0.23] : [0.09, 0.56, -0.24], brake)
      limb.elbow = blend(limb.elbow, [0.18, 1.52 - crouch, side * 0.43], brake)
      limb.hand = blend(limb.hand, [0.33, 1.24 - crouch, side * 0.49], brake)
    }
    if (hasBall) {
      limb.elbow = [0.28, 1.47, side * 0.42]
      limb.hand = [0.66, 1.38, side * 0.17]
    }
    if (jostle) {
      limb.foot = blend(limb.foot, [side === 1 ? 0.35 : -0.32, 0.24 - bob, side * 0.31], jostle * (1 - gait * 0.5))
      limb.knee = blend(limb.knee, [0.23, 0.57 - crouch * 0.24, side * 0.3], jostle * 0.5)
      if (side === contactSide) {
        limb.elbow = blend(limb.elbow, [0.28 + 0.11 * contactPulse, 1.63 - crouch, side * 0.48], jostle)
        limb.hand = blend(limb.hand, [0.65 + 0.12 * contactPulse, 1.52 - crouch, side * (hasBall ? 0.43 : 0.57)], jostle)
      } else if (!hasBall) {
        limb.elbow = blend(limb.elbow, [0.20, 1.46 - crouch, side * 0.47], jostle * 0.65)
        limb.hand = blend(limb.hand, [0.47, 1.35 - crouch, side * 0.44], jostle * 0.65)
      }
    }
    if (gather) {
      limb.foot = blend(limb.foot, [side === 1 ? 0.40 : -0.26, 0.24 - bob, side * 0.33], gather)
      limb.knee = blend(limb.knee, [side === 1 ? 0.53 : 0.10, 0.45 - crouch * 0.2, side * 0.30], gather)
      limb.elbow = blend(limb.elbow, [0.49, 1.24 - crouch, side * 0.43], gather)
      limb.hand = blend(limb.hand, [0.84, 0.99, side * 0.18], gather)
    }
    if (jump) {
      const reach = Math.min(1, jump / 0.6)
      limb.foot = blend(limb.foot, [side === 1 ? 0.36 : -0.31, 0.29, side * 0.31], reach)
      limb.knee = blend(limb.knee, [0.34, 0.69, side * 0.31], reach)
      limb.elbow = blend(limb.elbow, [0.35, 1.98 - crouch, side * 0.43], reach)
      limb.hand = blend(limb.hand, [0.72, 2.38 - crouch, side * 0.28], reach)
    }
    if (bump) {
      limb.foot = blend(limb.foot, [side === 1 ? 0.55 : -0.39, 0.24 - bob, side * 0.39], bump)
      limb.knee = blend(limb.knee, [side === 1 ? 0.47 : 0.03, 0.56 - crouch * 0.22, side * 0.33], bump)
      if (!hasBall || side === 1) {
        limb.elbow = blend(limb.elbow, [0.18, 1.58 - crouch, side * 0.61], bump)
        limb.hand = blend(limb.hand, [0.47, 1.40 - crouch, side * 0.82], bump)
      }
    }
    if (kick) {
      if (side === 1) {
        const stroke = dt < -0.08
          ? -0.63 + smooth(-0.32, -0.08, dt) * 0.22
          : dt < 0.13 ? -0.41 + smooth(-0.08, 0.13, dt) * 1.43
            : 1.02 - smooth(0.13, 0.55, dt) * 0.91
        limb.foot = blend(limb.foot, [stroke, 0.26 + 0.45 * smooth(-0.08, 0.14, dt) * (1 - smooth(0.22, 0.55, dt)), side * 0.25], kick)
        limb.knee = blend(limb.knee, [Math.max(0.17, stroke * 0.62 + 0.2), 0.83, side * 0.25], kick)
      } else {
        limb.foot = blend(limb.foot, [-0.22, 0.15, side * 0.3], kick)
        limb.knee = blend(limb.knee, [0.09, 0.54, side * 0.29], kick)
      }
      limb.elbow = blend(limb.elbow, [-0.17, 1.54, side * 0.6], kick)
      limb.hand = blend(limb.hand, [-0.18, 1.46, side * 0.88], kick)
    }
    if (handball) {
      // The left hand cups the ball. The right fist winds back past the shoulder,
      // crosses the body at release, and finishes fully extended.
      limb.elbow = blend(limb.elbow, side === 1
        ? [-0.28 + punch * 0.87, 1.65 - punch * 0.17, 0.58 - punch * 0.34]
        : [0.35, 1.45, -0.46], handball)
      limb.hand = blend(limb.hand, side === 1
        ? [-0.58 + punch * 1.95, 1.72 - punch * 0.29, 0.49 - punch * 0.38]
        : [0.72, 1.33, -0.12], handball)
    }
    if (catchWeight && !jump) {
      limb.elbow = blend(limb.elbow, [0.46, 1.87 - crouch, side * 0.44], catchWeight)
      limb.hand = blend(limb.hand, [0.82, 2.08 - crouch, side * 0.23], catchWeight)
    }
    if (tackle) {
      limb.elbow = blend(limb.elbow, [0.45, 1.39 - crouch, side * 0.46], tackle)
      limb.hand = blend(limb.hand, [0.98, 1.19 - crouch, side * 0.36], tackle)
      limb.foot = blend(limb.foot, [side === 1 ? 0.48 : -0.36, 0.16, side * 0.37], tackle)
      limb.knee = blend(limb.knee, [side === 1 ? 0.54 : -0.04, 0.53 - crouch * 0.35, side * 0.3], tackle)
    }
    return limb
  }) as [Limb, Limb]

  let ball: Point3 = [0.67 - jostle * 0.08, 1.39 + jostle * 0.04, -contactSide * jostle * 0.12]
  if (gather && hasBall) {
    ball = blend(ball, [0.80, 1.03, 0], gather * (1 - smooth(0.04, 0.43, dt)))
  } else if (catchWeight && hasBall) {
    ball = blend(ball, [0.76, action?.airborne ? 2.38 - crouch : 2.0 - crouch, 0], catchWeight)
  } else if (action?.kind === 'kick' && hasBall) {
    ball = blend(ball, [0.84, 0.33, 0.14], smooth(-0.20, -0.015, dt))
  } else if (action?.kind === 'handball' && hasBall) {
    ball = blend(ball, [0.75 + smooth(-0.11, 0, dt) * 0.22, 1.36, -0.12], handball)
  }
  const expression: Expression = tackle > 0.35 ? 'tackling' : bump > 0.4 ? 'bumping' :
    kick > 0.34 ? 'kicking' : handball > 0.34 ? 'handballing' :
      gather > 0.3 ? 'gathering' : contest > 0.3 ? 'contesting' : catchWeight > 0.3 ? 'catching' :
        jostle > 0.35 ? hasBall ? 'protecting' : 'jostling' :
          hasBall ? 'carrying' : pace === 'sprint' ? 'sprinting' : pace === 'jog' ? 'jogging' : 'neutral'
  return { pace, sprint, transition: transitionWeight > 0.05 ? transition?.kind ?? null : null,
    heading, bob, jump, leap, lean, twist, roll, crouch, limbs, ball, expression }
}
