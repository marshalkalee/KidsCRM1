import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const SOURCE_ROOT = path.resolve('src')
const dictionarySources = Object.fromEntries(
  ['en', 'kk'].map(language => [
    language,
    fs.readFileSync(path.join(SOURCE_ROOT, 'i18n', `${language}.json`), 'utf8'),
  ])
)
const dictionaries = Object.fromEntries(
  Object.entries(dictionarySources).map(([language, source]) => [language, JSON.parse(source)])
)

// Keys passed to t() indirectly through status/reason maps cannot be found
// by the literal-call scan below, so keep their contract explicit here.
const DYNAMIC_KEYS = [
  'Запланировано', 'Проведено', 'Отменено', 'Перенесено',
  'Болезнь преподавателя', 'Праздник', 'Авария в помещении', 'Другое',
  'Болезнь', 'Семейные обстоятельства', 'Без причины',
  'Нет абонемента', 'Абонемент заморожен', 'Занятия закончились',
  'Абонемент не позволяет списание', 'Девочка', 'Мальчик', 'Отработка', 'Пробное',
  'Посещено', 'Пропущено',
  'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс',
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
  'plural:день',
]

function sourceFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const fullPath = path.join(directory, entry.name)
    if (entry.isDirectory()) return sourceFiles(fullPath)
    return /\.(js|jsx)$/.test(entry.name) ? [fullPath] : []
  })
}

const keys = new Set()
const literalPattern = /\bt\(\s*(['"])((?:\\.|(?!\1).)*)\1/g

for (const file of sourceFiles(SOURCE_ROOT)) {
  const source = fs.readFileSync(file, 'utf8')
  for (const match of source.matchAll(literalPattern)) keys.add(match[2])
}
DYNAMIC_KEYS.forEach(key => keys.add(key))

let failed = false
for (const [language, dictionary] of Object.entries(dictionaries)) {
  const rawKeys = [...dictionarySources[language].matchAll(/^\s*"((?:\\.|[^"])*)"\s*:/gm)].map(match => match[1])
  const duplicateKeys = [...new Set(rawKeys.filter((key, index) => rawKeys.indexOf(key) !== index))]
  if (duplicateKeys.length > 0) {
    failed = true
    console.error(`${language}: duplicate translation key(s)`)
    duplicateKeys.forEach(key => console.error(`  ${key}`))
  }
  const missing = [...keys].filter(key => !(key in dictionary)).sort((a, b) => a.localeCompare(b, 'ru'))
  if (missing.length === 0) continue
  failed = true
  console.error(`${language}: missing ${missing.length} translation key(s)`)
  missing.forEach(key => console.error(`  ${key}`))
}

if (failed) process.exitCode = 1
else console.log(`i18n: ${keys.size} literal keys are present in EN and KK dictionaries`)
