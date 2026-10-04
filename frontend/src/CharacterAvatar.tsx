import { useState } from 'react'
import type { PersonalityProfile } from './types'

const EMOTION_MOOD: Record<string, string> = {
  азарт: 'attack',
  напор: 'attack',
  тревога: 'danger',
  смирение: 'sad',
  удовлетворение: 'happy',
  облегчение: 'happy',
  принципиальность: 'thinking',
  сосредоточенность: 'thinking',
  задумчивость: 'thinking',
}

interface Props {
  personality: PersonalityProfile | undefined
  emotion?: string | null
  thinking?: boolean
  result?: string | null
  compact?: boolean
}

function moodFor(emotion: string | null | undefined, thinking: boolean, result: string | null | undefined): string {
  if (result === '0-1') return 'happy'
  if (result === '1-0') return 'sad'
  if (thinking) return 'thinking'
  return EMOTION_MOOD[emotion ?? ''] ?? 'default'
}

export function CharacterAvatar({ personality, emotion = null, thinking = false, result = null, compact = false }: Props) {
  const mood = moodFor(emotion, thinking, result)
  const [failedSrc, setFailedSrc] = useState<string | null>(null)
  const src = personality?.avatars?.[mood] ?? personality?.avatars?.default
  const initials = personality?.name
    .split(/\s+/)
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase() ?? 'CV'

  return (
    <div className={`character-avatar mood-${mood}${compact ? ' character-avatar-compact' : ''}`} title={`${personality?.name ?? 'Персонаж'} · ${mood}`}>
      {src && failedSrc !== src
        ? <img src={src} alt={`${personality?.name ?? 'Персонаж'}: ${mood}`} onError={() => setFailedSrc(src)} />
        : <span>{initials}</span>}
    </div>
  )
}
