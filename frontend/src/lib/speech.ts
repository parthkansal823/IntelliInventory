/** Free, in-browser voice features (Web Speech API) - no server or API cost. */

export const canSpeak = () => typeof window !== 'undefined' && 'speechSynthesis' in window

export function plainText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/\|.*\|/g, ' ')
    .replace(/[#*_`>~-]+/g, ' ')
    .replace(/\[(.*?)\]\(.*?\)/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()
}

export function speak(markdown: string, onEnd?: () => void) {
  if (!canSpeak()) return
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(plainText(markdown).slice(0, 4000))
  utterance.rate = 1.03
  utterance.onend = () => onEnd?.()
  window.speechSynthesis.speak(utterance)
}

export const stopSpeaking = () => canSpeak() && window.speechSynthesis.cancel()

type Recognition = {
  lang: string
  interimResults: boolean
  continuous: boolean
  start: () => void
  stop: () => void
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null
  onend: (() => void) | null
  onerror: ((e: { error: string }) => void) | null
}

export function createRecognition(lang = 'en-IN'): Recognition | null {
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition }
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition
  if (!Ctor) return null
  const r = new Ctor()
  r.lang = lang
  r.interimResults = true
  r.continuous = false
  return r
}
