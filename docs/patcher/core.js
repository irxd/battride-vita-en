// Patcher logic without any page code, so it runs the same in the browser and in Node (for testing).
// The player picks the decrypted game folder (ux0:app/PCSG00675) and update folder (ux0:patch/PCSG00675);
// every manifest entry names the original file by path, size and SHA-1, and the file it becomes in rePatch.

import { applyPatch, PatchError } from './vcdiff.js';

export { PatchError };

export async function sha1(blob) {
  const d = await crypto.subtle.digest('SHA-1', await blob.arrayBuffer());
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** Path of a picked file relative to its folder, with / separators. */
export function filePath(file) {
  return (file.webkitRelativePath || file.relPath || file.name).replace(/\\/g, '/');
}

/** Manifest entries whose original could be this file (same path tail and size). */
export function candidates(file, manifest) {
  const p = '/' + filePath(file).toLowerCase();
  return manifest.files.filter((e) => p.endsWith('/' + e.source.path.toLowerCase()) && e.source.size === file.size);
}

/**
 * Check one file. Returns { entry, ok, message } or null when the path is not one we patch.
 * ok=false: right path and size, but not the expected content (encrypted, already patched, other version).
 */
export async function identify(file, manifest) {
  const p = '/' + filePath(file).toLowerCase();
  const byPath = manifest.files.filter((e) => p.endsWith('/' + e.source.path.toLowerCase()));
  if (!byPath.length) return null;
  const sized = byPath.filter((e) => e.source.size === file.size);
  const h = await sha1(file);
  const e = sized.find((x) => x.source.sha1 === h);
  if (e) return { entry: e, ok: true };
  if (byPath.some((x) => x.target.sha1 === h))
    return { entry: byPath[0], ok: false, message: 'already patched' };
  return { entry: byPath[0], ok: false, message: 'different file (encrypted, or game version 1.00 instead of 1.02)' };
}

/**
 * Patch one file. `sink` gets the output: { write(Uint8Array): Promise, close(): Promise, abort(): Promise }.
 * onProgress(bytesDoneForThisFile). Throws PatchError with a readable message if the source doesn't match.
 */
export async function patchFile(file, entry, patchBytes, sink, onProgress) {
  const readSource = async (pos, len) => new Uint8Array(await file.slice(pos, pos + len).arrayBuffer());
  try {
    const size = await applyPatch(patchBytes, readSource, (w) => sink.write(w), onProgress);
    if (size !== entry.target.size) throw new PatchError('patched size is wrong');
    await sink.close();
  } catch (err) {
    await sink.abort?.();
    if (err instanceof PatchError && /checksum mismatch|too short/.test(err.message))
      throw new PatchError(`${entry.source.path} doesn't match this patch. Make sure it is the original, decrypted ` +
        'file from game version 1.02 and not already patched.');
    throw err;
  }
}
