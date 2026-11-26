import { useId, type CSSProperties } from 'react'
import './signal.css'

const tau = Math.PI * 2
const sections = 80
const samples = 48

// Tilt each elliptical glass rib around the spine of an undulating torus.
function rib(angle: number, pose: number) {
  const twist = angle + 0.4 + pose * Math.sin(angle - 0.6)
  const depth = Math.sin(angle)
  const outline: string[] = []

  for (let step = 0; step < samples; step++) {
    const cross = (step / samples) * tau
    const wide = 30 * Math.cos(cross)
    const thin = 12 * Math.sin(cross)
    const radial = 70 + wide * Math.cos(twist) - thin * Math.sin(twist)
    const height = wide * Math.sin(twist) + thin * Math.cos(twist)
      + (13 + pose * 9) * Math.sin(2 * angle + 0.4)
    const x = radial * Math.cos(angle)
    const y = radial * depth * 0.49 - height * 0.87
    const perspective = 400 / (400 - 0.38 * radial * depth)
    const u = 163 + (x * 0.95 + y * 0.31) * perspective
    const v = 79 + (y * 0.95 - x * 0.31) * perspective
    outline.push(`${step === 0 ? 'M' : 'L'}${u.toFixed(2)} ${v.toFixed(2)}`)
  }

  return outline.join(' ') + 'Z'
}

const ribs = Array.from({ length: sections }, (_, i) => {
  const angle = (i / sections) * tau
  const rest = rib(angle, 0)
  return {
    angle,
    depth: Math.sin(angle),
    rest,
    style: {
      '--signal-rest': `path("${rest}")`,
      '--signal-turn': `path("${rib(angle, 0.38)}")`,
      '--signal-return': `path("${rib(angle, -0.23)}")`,
    } as CSSProperties,
  }
}).sort((a, b) => a.depth - b.depth)

export function Signal() {
  const id = useId().replace(/[^\w-]/g, '')
  return (
    <div className="signal-art" aria-hidden="true">
      <svg viewBox="0 0 306 156" focusable="false">
        <defs>
          <linearGradient id={id + 'rim'} x1="0.05" y1="0" x2="0.9" y2="1">
            <stop stopColor="#e6f3ff" />
            <stop offset=".19" stopColor="#665b96" />
            <stop offset=".42" stopColor="#352b62" />
            <stop offset=".55" stopColor="#ccc7ff" />
            <stop offset=".62" stopColor="#514579" />
            <stop offset="1" stopColor="#292443" />
          </linearGradient>
          <linearGradient id={id + 'glass'} x2=".7" y2="1">
            <stop stopColor="#dce9f6" />
            <stop offset=".46" stopColor="#9487c1" />
            <stop offset="1" stopColor="#636499" />
          </linearGradient>
        </defs>
        <g className="signal-art__orbit">
          {ribs.map(({ angle, depth, rest, style }) => (
            <path
              key={angle}
              className="signal-art__rib"
              d={rest}
              style={style}
              fill={`url(#${id}glass)`}
              fillOpacity={0.05 + (depth + 1) * 0.027}
              stroke={`url(#${id}rim)`}
              strokeOpacity={0.56 + (depth + 1) * 0.20}
              strokeWidth={0.82 + (depth + 1) * 0.12}
              strokeLinejoin="round"
            />
          ))}
        </g>
      </svg>
    </div>
  )
}
