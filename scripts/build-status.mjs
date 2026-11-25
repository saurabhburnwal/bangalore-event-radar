import {readFileSync, writeFileSync} from 'node:fs'

const read = name => readFileSync(new URL('../status/' + name, import.meta.url), 'utf8')
const metrics = read('metrics.mjs').replaceAll('export function ', 'function ')
const app = read('status.mjs').replace(/^import .* from '\.\/metrics\.mjs'\n/, '')
const page = read('index.html')
  .replace('<link rel="stylesheet" href="status.css">', () => '<style>\n' + read('status.css') + '</style>')
  .replace('<script type="module" src="status.mjs"></script>', () => '<script type="module">\n' + metrics + '\n' + app + '\n</script>')
writeFileSync(process.argv[2], page)
