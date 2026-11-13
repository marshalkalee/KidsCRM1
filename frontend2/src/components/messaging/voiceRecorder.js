import { useEffect, useRef, useState } from 'react'

/*
 * Запись голосового из браузера (MediaRecorder): пауза и продолжение, после
 * остановки — прослушать (preview) и отправить или удалить. Готовая запись —
 * обычный File: уходит в WhatsApp как голосовое (Evolution перекодирует ffmpeg).
 * Микрофон работает только на https или localhost — так требует браузер.
 *
 * level (0–1) — громкость с микрофона для индикатора: видно, что запись
 * слышит голос. Если за всю запись звука не было (выбран не тот микрофон,
 * он выключен или Windows не даёт доступа) — тишину не отправляем.
 */

// Тише этого — тишина: громкость обычной речи на порядок выше.
const SILENCE_LEVEL = 0.02

const FORMATS = [
  ['audio/webm;codecs=opus', 'webm'],
  ['audio/webm', 'webm'],
  ['audio/mp4', 'm4a'],
  ['audio/ogg;codecs=opus', 'ogg'],
]

export const VOICE_SUPPORTED =
  typeof window !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia) && 'MediaRecorder' in window

export function useVoiceRecorder({ onRecorded, onError, maxSeconds = 300 }) {
  const [recording, setRecording] = useState(false)
  const [paused, setPaused] = useState(false)
  const [preview, setPreview] = useState(null)
  const [seconds, setSeconds] = useState(0)
  const [level, setLevel] = useState(0)
  const recorder = useRef(null)
  const audio = useRef(null)
  const peak = useRef(0)
  const stream = useRef(null)
  const chunks = useRef([])
  const timer = useRef(null)
  const keep = useRef(true)

  function release() {
    window.clearInterval(timer.current)
    audio.current?.close().catch(() => {})
    audio.current = null
    setLevel(0)
    stream.current?.getTracks().forEach(track => track.stop())
    stream.current = null
    recorder.current = null
    setRecording(false)
    setPaused(false)
  }

  function tickTimer() {
    window.clearInterval(timer.current)
    timer.current = window.setInterval(() => {
      setSeconds(value => {
        // Длинная запись — останавливаем сами и даём прослушать.
        if (value + 1 >= maxSeconds) stop(true)
        return value + 1
      })
    }, 1000)
  }

  function pause() {
    if (recorder.current?.state !== 'recording') return
    recorder.current.pause()
    window.clearInterval(timer.current)
    setPaused(true)
  }

  function resume() {
    if (recorder.current?.state !== 'paused') return
    recorder.current.resume()
    tickTimer()
    setPaused(false)
  }

  function discard() {
    if (preview) URL.revokeObjectURL(preview.url)
    setPreview(null)
  }

  function send() {
    if (!preview) return
    onRecorded(preview.file)
    discard()
  }

  function stop(send) {
    keep.current = send
    if (recorder.current && recorder.current.state !== 'inactive') recorder.current.stop()
    else release()
  }

  async function start() {
    if (!VOICE_SUPPORTED || recording) return
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      onError?.('microphone')
      return
    }
    const [mimeType, ext] = FORMATS.find(([type]) => MediaRecorder.isTypeSupported(type)) || ['', 'webm']
    const media = new MediaRecorder(stream.current, mimeType ? { mimeType } : undefined)
    chunks.current = []
    keep.current = true
    media.ondataavailable = event => { if (event.data.size) chunks.current.push(event.data) }
    media.onstop = () => {
      const type = media.mimeType || mimeType || 'audio/webm'
      const blob = new Blob(chunks.current, { type })
      const heard = peak.current >= SILENCE_LEVEL
      release()
      if (keep.current && !heard) {
        onError?.('silent')
        return
      }
      if (keep.current && blob.size) {
        // Сначала прослушать: отправка — отдельной кнопкой.
        const file = new File([blob], `голосовое.${ext}`, { type: type.split(';')[0] })
        setPreview({ file, url: URL.createObjectURL(blob) })
      }
    }
    recorder.current = media
    listen(stream.current)
    media.start()
    setSeconds(0)
    setRecording(true)
    tickTimer()
  }

  // Громкость с микрофона: AnalyserNode, 10 раз в секунду.
  function listen(source) {
    peak.current = 0
    try {
      const context = new (window.AudioContext || window.webkitAudioContext)()
      const analyser = context.createAnalyser()
      analyser.fftSize = 512
      context.createMediaStreamSource(source).connect(analyser)
      audio.current = context
      // Разрешение на микрофон приходит уже после клика — браузер может
      // держать анализатор на паузе. Тогда тишину не проверяем, чтобы не
      // выбросить нормальную запись.
      context.resume?.().catch(() => {})
      const samples = new Float32Array(analyser.fftSize)
      const tick = () => {
        if (!audio.current) return
        if (context.state !== 'running') {
          peak.current = 1
          window.setTimeout(tick, 100)
          return
        }
        analyser.getFloatTimeDomainData(samples)
        let sum = 0
        for (const value of samples) sum += value * value
        const rms = Math.sqrt(sum / samples.length)
        peak.current = Math.max(peak.current, rms)
        setLevel(Math.min(1, rms * 6))
        window.setTimeout(tick, 100)
      }
      tick()
    } catch {
      // Без индикатора запись всё равно идёт; тишину тогда не проверить.
      peak.current = 1
    }
  }

  // Ушли со страницы во время записи — микрофон не держим.
  useEffect(() => () => {
    keep.current = false
    window.clearInterval(timer.current)
    audio.current?.close().catch(() => {})
    stream.current?.getTracks().forEach(track => track.stop())
  }, [])

  return {
    recording,
    paused,
    preview,
    seconds,
    level,
    start,
    pause,
    resume,
    finish: () => stop(true),
    cancel: () => stop(false),
    send,
    discard,
  }
}
