export const PHONE_MAX_LENGTH = 11
export const NAME_MAX_LENGTH = 255

export function phoneDigits(value) {
  const raw = String(value ?? '')
  let digits = raw.replace(/\D/g, '').slice(0, PHONE_MAX_LENGTH)
  // «8 701…» без плюса — местный формат того же +7 (так его понимает и
  // сервер); иначе в поле оставалось «+8701…», похожее на ошибку.
  if (digits.startsWith('8') && !raw.trimStart().startsWith('+')) digits = `7${digits.slice(1)}`
  // Храним значение поля в привычном международном виде. Важно очищать всю
  // вставленную строку до ограничения количества цифр: иначе пробелы, скобки
  // и дефисы занимают maxLength, и браузер отбрасывает конец номера.
  if (digits) return `+${digits}`
  return raw.includes('+') ? '+' : ''
}

export function personNameInput(value) {
  return Array.from(String(value ?? ''))
    .filter(char => /[\p{L}\s'’-]/u.test(char))
    .join('')
    .slice(0, NAME_MAX_LENGTH)
}

export const personNameInputProps = {
  minLength: 2,
  maxLength: NAME_MAX_LENGTH,
}

export const entityNameInputProps = {
  minLength: 2,
  maxLength: NAME_MAX_LENGTH,
}

export const phoneInputProps = {
  type: 'tel',
  inputMode: 'tel',
  minLength: 11,
  pattern: '\\+?(?:[78]\\d{10}|\\d{10})',
}
