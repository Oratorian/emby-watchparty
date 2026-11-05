const MAX_ARCHIVE = 1024 * 1024
const MAX_EXPANDED = 2 * 1024 * 1024
const encoder = new TextEncoder()
const decoder = new TextDecoder('utf-8', { fatal: true })
const filenameDecoder = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true })
const filename = /^[A-Za-z][A-Za-z0-9_-]*\.json$/
const crcTable = Uint32Array.from({ length: 256 }, (_, index) => {
  let crc = index
  for (let bit = 0; bit < 8; bit++) crc = crc & 1 ? 0xedb88320 ^ (crc >>> 1) : crc >>> 1
  return crc >>> 0
})

function crc32(bytes) {
  let crc = 0xffffffff
  for (const byte of bytes) crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8)
  return (crc ^ 0xffffffff) >>> 0
}

function join(chunks, length = chunks.reduce((size, chunk) => size + chunk.length, 0)) {
  const result = new Uint8Array(length)
  let offset = 0
  for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.length }
  return result
}

function safeName(name) {
  if (!filename.test(name)) throw new Error('The ZIP must contain only root-level language JSON files.')
}

export function encodeZip(files) {
  const entries = Object.entries(files)
  if (!entries.length || entries.length > 32) throw new Error('A language ZIP must contain between 1 and 32 files.')
  const local = []
  const directory = []
  let offset = 0
  let expanded = 0
  const seen = new Set()
  for (const [name, text] of entries) {
    safeName(name)
    if (typeof text !== 'string') throw new Error('Language ZIP files must contain text.')
    if (seen.has(name.toLowerCase())) throw new Error('Duplicate ZIP filenames are not allowed.')
    seen.add(name.toLowerCase())
    const nameBytes = encoder.encode(name)
    const bytes = encoder.encode(text)
    expanded += bytes.length
    if (expanded > MAX_EXPANDED) throw new Error('Expanded language files must fit within 2 MiB.')
    const checksum = crc32(bytes)
    const header = new Uint8Array(30 + nameBytes.length)
    const view = new DataView(header.buffer)
    view.setUint32(0, 0x04034b50, true)
    view.setUint16(4, 20, true)
    view.setUint16(6, 0x800, true)
    view.setUint16(12, 33, true)
    view.setUint32(14, checksum, true)
    view.setUint32(18, bytes.length, true)
    view.setUint32(22, bytes.length, true)
    view.setUint16(26, nameBytes.length, true)
    header.set(nameBytes, 30)
    local.push(header, bytes)
    const central = new Uint8Array(46 + nameBytes.length)
    const table = new DataView(central.buffer)
    table.setUint32(0, 0x02014b50, true)
    table.setUint16(4, 0x0314, true)
    table.setUint16(6, 20, true)
    table.setUint16(8, 0x800, true)
    table.setUint16(14, 33, true)
    table.setUint32(16, checksum, true)
    table.setUint32(20, bytes.length, true)
    table.setUint32(24, bytes.length, true)
    table.setUint16(28, nameBytes.length, true)
    table.setUint32(38, (0o100644 << 16) >>> 0, true)
    table.setUint32(42, offset, true)
    central.set(nameBytes, 46)
    directory.push(central)
    offset += header.length + bytes.length
  }
  const directoryBytes = join(directory)
  const ending = new Uint8Array(22)
  const end = new DataView(ending.buffer)
  end.setUint32(0, 0x06054b50, true)
  end.setUint16(8, entries.length, true)
  end.setUint16(10, entries.length, true)
  end.setUint32(12, directoryBytes.length, true)
  end.setUint32(16, offset, true)
  const archive = join([...local, directoryBytes, ending])
  if (archive.length > MAX_ARCHIVE) throw new Error('This ZIP exceeds the 1 MiB upload limit. Export fewer or shorter translations.')
  return archive
}

async function inflate(bytes, limit) {
  if (typeof DecompressionStream === 'undefined') throw new Error('This browser cannot open compressed ZIPs. Try a current browser or a stored ZIP.')
  let stream
  try { stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw')) } catch {
    throw new Error('This browser cannot open deflate ZIPs. Try a current browser or a stored ZIP.')
  }
  const reader = stream.getReader()
  const chunks = []
  let size = 0
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) return join(chunks, size)
      size += value.length
      if (size > limit) throw new Error('Expanded language files must fit within 2 MiB.')
      chunks.push(value)
    }
  } finally { await reader.cancel().catch(() => {}) }
}

export async function decodeZip(input) {
  const bytes = input instanceof Uint8Array ? input : new Uint8Array(input)
  if (bytes.length < 22 || bytes.length > MAX_ARCHIVE) throw new Error('Choose a valid ZIP no larger than 1 MiB.')
  const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  let ending = -1
  for (let index = bytes.length - 22; index >= Math.max(0, bytes.length - 65557); index--) {
    if (data.getUint32(index, true) === 0x06054b50 && index + 22 + data.getUint16(index + 20, true) === bytes.length) {
      ending = index
      break
    }
  }
  if (ending < 0 || data.getUint16(ending + 4, true) || data.getUint16(ending + 6, true)) throw new Error('Unsupported or damaged ZIP archive.')
  const count = data.getUint16(ending + 10, true)
  const directorySize = data.getUint32(ending + 12, true)
  const directoryOffset = data.getUint32(ending + 16, true)
  if (!count || count > 32 || count !== data.getUint16(ending + 8, true) || directoryOffset + directorySize !== ending) throw new Error('Unsupported ZIP directory.')
  const files = Object.create(null)
  const seen = new Set()
  const ranges = []
  let cursor = directoryOffset
  let expanded = 0
  for (let number = 0; number < count; number++) {
    if (cursor + 46 > ending || data.getUint32(cursor, true) !== 0x02014b50) throw new Error('Damaged ZIP directory.')
    const flags = data.getUint16(cursor + 8, true)
    const method = data.getUint16(cursor + 10, true)
    const checksum = data.getUint32(cursor + 16, true)
    const compressed = data.getUint32(cursor + 20, true)
    const size = data.getUint32(cursor + 24, true)
    const nameLength = data.getUint16(cursor + 28, true)
    const extraLength = data.getUint16(cursor + 30, true)
    const commentLength = data.getUint16(cursor + 32, true)
    const mode = data.getUint32(cursor + 38, true)
    const localOffset = data.getUint32(cursor + 42, true)
    if (cursor + 46 + nameLength + extraLength + commentLength > ending) throw new Error('Damaged ZIP filename.')
    const name = filenameDecoder.decode(bytes.subarray(cursor + 46, cursor + 46 + nameLength))
    safeName(name)
    if (seen.has(name.toLowerCase())) throw new Error('Duplicate ZIP filenames are not allowed.')
    seen.add(name.toLowerCase())
    if (flags & 0x2041 || ![0, 8].includes(method) || data.getUint16(cursor + 34, true)
      || ![0, 0x8000].includes((mode >>> 16) & 0xf000) || mode & 0x10) throw new Error('Encrypted, linked or unsupported ZIP members are not allowed.')
    expanded += size
    if (expanded > MAX_EXPANDED || size === 0xffffffff || compressed === 0xffffffff) throw new Error('Expanded language files must fit within 2 MiB.')
    if (localOffset + 30 > directoryOffset || data.getUint32(localOffset, true) !== 0x04034b50) throw new Error('Damaged ZIP member header.')
    const localNameLength = data.getUint16(localOffset + 26, true)
    const start = localOffset + 30 + localNameLength + data.getUint16(localOffset + 28, true)
    if (start + compressed > directoryOffset || data.getUint16(localOffset + 6, true) !== flags
      || data.getUint16(localOffset + 8, true) !== method
      || filenameDecoder.decode(bytes.subarray(localOffset + 30, localOffset + 30 + localNameLength)) !== name) throw new Error('ZIP member headers do not match.')
    if (ranges.some(([left, right]) => localOffset < right && start + compressed > left)) throw new Error('ZIP members overlap.')
    ranges.push([localOffset, start + compressed])
    const payload = bytes.subarray(start, start + compressed)
    const content = method === 0 ? payload : await inflate(payload, Math.min(size, MAX_EXPANDED))
    if (content.length !== size || crc32(content) !== checksum) throw new Error(`ZIP checksum or size mismatch: ${name}.`)
    files[name] = decoder.decode(content)
    cursor += 46 + nameLength + extraLength + commentLength
  }
  if (cursor !== ending) throw new Error('The ZIP contains unexpected directory data.')
  return files
}
