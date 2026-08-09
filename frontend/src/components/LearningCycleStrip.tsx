import { ArrowRight, CheckCircle2 } from 'lucide-react'
import type { TeachingCycle } from '../api/client'
import { phaseMeta, recommendationCopy, TEACHING_PHASES } from '../learningPresentation'

export function LearningCycleStrip({
  cycle,
  compact = false,
}: {
  cycle: TeachingCycle
  compact?: boolean
}) {
  const currentIndex = TEACHING_PHASES.findIndex((item) => item.id === cycle.phase)
  const current = phaseMeta(cycle.phase)

  return (
    <section className={`learning-cycle-strip${compact ? ' compact' : ''}`} aria-label="当前教学进度">
      <div className="learning-cycle-copy">
        <span>{current.label}</span>
        <strong>{cycle.title}</strong>
        <small>{recommendationCopy(cycle.recommendation)}</small>
      </div>
      <ol className="learning-cycle-rail" aria-label={`当前阶段：${current.label}`}>
        {TEACHING_PHASES.map((phase, index) => {
          const state = index < currentIndex ? 'complete' : index === currentIndex ? 'current' : 'upcoming'
          return (
            <li className={state} key={phase.id} aria-current={state === 'current' ? 'step' : undefined}>
              <span className="learning-cycle-marker" aria-hidden="true">
                {state === 'complete' ? <CheckCircle2 size={13} /> : index + 1}
              </span>
              <span>{phase.shortLabel}</span>
            </li>
          )
        })}
      </ol>
      {!compact && (
        <p className="learning-cycle-next">
          {current.description}
          {cycle.recommendation.action === 'transition' && <ArrowRight size={14} aria-hidden="true" />}
        </p>
      )}
    </section>
  )
}
