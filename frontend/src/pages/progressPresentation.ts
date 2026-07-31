import type { ProgressTrendSample } from '../api/client'

export function buildTrendGeometry(
  samples: ProgressTrendSample[],
  target: number | null,
  width = 360,
  height = 130,
  padding = 18,
) {
  const points = samples.map((sample, index) => ({
    ...sample,
    x: samples.length === 1
      ? width / 2
      : padding + index * ((width - padding * 2) / (samples.length - 1)),
    y: height - padding - (sample.band / 9) * (height - padding * 2),
  }))
  const eligible = points.filter((point) => point.eligible)
  return {
    points,
    path: eligible
      .map((point, index) => `${index ? 'L' : 'M'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`)
      .join(' '),
    targetY: target == null
      ? null
      : height - padding - (target / 9) * (height - padding * 2),
  }
}
