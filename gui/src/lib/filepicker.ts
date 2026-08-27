import { invoke } from '@tauri-apps/api/core';
import { open } from '@tauri-apps/plugin-dialog';
import { readDir } from '@tauri-apps/plugin-fs';

/**
 * Grant the fs plugin access to user-selected paths.
 *
 * The static `fs:scope` in capabilities/default.json is empty, so nothing is
 * readable until it passes through here. Call this for every path that enters
 * the app — a dialog pick or a drag-drop — before any fs operation on it.
 */
export async function grantPathAccess(paths: string[]): Promise<void> {
  if (paths.length === 0) return;
  await invoke('grant_path_access', { paths });
}

/**
 * Expand a folder path into its contained PDF file paths (non-recursive).
 * Returns full absolute paths for each .pdf file found.
 */
export async function expandFolder(folderPath: string): Promise<string[]> {
  const clean = folderPath.replace(/[\\/]+$/, '');
  const sep = clean.includes('\\') ? '\\' : '/';
  await grantPathAccess([clean]);
  const entries = await readDir(clean);
  return entries
    .filter((e) => e.isFile && e.name.toLowerCase().endsWith('.pdf'))
    .map((e) => clean + sep + e.name);
}

export async function pickPdfFiles(): Promise<string[]> {
  const result = await open({
    multiple: true,
    filters: [{ name: 'PDF Files', extensions: ['pdf'] }],
  });
  if (!result) return [];
  const paths = Array.isArray(result) ? result : [result];
  await grantPathAccess(paths);
  return paths;
}

/**
 * Open a folder picker and return the PDF files inside it.
 * Returns null if the user cancelled, or an array of PDF paths (possibly empty).
 */
export async function pickFolder(): Promise<string[] | null> {
  const folder = await open({ directory: true, multiple: false }) as string | null;
  if (!folder) return null;
  return expandFolder(folder);
}
