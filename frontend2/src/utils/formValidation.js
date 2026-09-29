export const PHONE_MAX_LENGTH = 11
export const NAME_MAX_LENGTH = 255

export function phoneDigits(value) {
  return String(value ?? '').replace(/\D/g, '').slice(0, PHONE_MAX_LENGTH)
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
  inputMode: 'numeric',
  minLength: 10,
  maxLength: PHONE_MAX_LENGTH,
  pattern: '(?:[78]\\d{10}|\\d{10})',
}
