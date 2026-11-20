// Browser features for working from the screen: whole-screen eyedropper, one-frame
// screen capture, and images pasted from the clipboard.
// EyeDropper and getDisplayMedia exist only in Chrome / Edge on a computer, and only
// on localhost or HTTPS, so callers check the *Supported() functions first.
import { fromHex } from './color.js';

export const UNSUPPORTED_HINT = 'Needs Chrome or Edge on a computer.';

const pad = (n) => String(n).padStart(2, '0');

function stamp(d = new Date()) {
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

const cancelled = (err) => ['AbortError', 'NotAllowedError'].includes(err?.name);

// ---- Eyedropper ------------------------------------------------------------ //
export function screenPickSupported() {
  return typeof window !== 'undefined' && 'EyeDropper' in window;
}

/** Let the user click any pixel on the screen. Resolves {r, g, b, hex}, or null if they press Esc. */
export async function pickScreenColor() {
  if (!screenPickSupported()) throw new Error(UNSUPPORTED_HINT);
  let result;
  try {
    result = await new window.EyeDropper().open();
  } catch (err) {
    if (cancelled(err)) return null;
    throw err;
  }
  const rgb = fromHex(result.sRGBHex);
  if (!rgb) throw new Error('The browser returned a color this page cannot read.');
  return { ...rgb, hex: result.sRGBHex.toUpperCase() };
}

// ---- Screen capture -------------------------------------------------------- //
export function captureSupported() {
  return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getDisplayMedia;
}

const wait = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

/**
 * Ask the browser which screen / window / tab to share, grab one frame and stop sharing.
 * Resolves a PNG File named screen-YYYYMMDD-HHMMSS.png, or null if the user cancels the chooser.
 */
export async function captureScreenFile() {
  if (!captureSupported()) throw new Error(UNSUPPORTED_HINT);
  let stream;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
  } catch (err) {
    if (cancelled(err)) return null;
    throw err;
  }
  try {
    const video = document.createElement('video');
    video.muted = true;
    video.srcObject = stream;
    await video.play();
    // The chooser dialog takes a moment to leave the screen; do not photograph it.
    await wait(400);
    if (!video.videoWidth || !video.videoHeight) throw new Error('The screen could not be captured. Try again.');
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);
    video.srcObject = null;
    const blob = await new Promise((resolve) => { canvas.toBlob(resolve, 'image/png'); });
    if (!blob) throw new Error('The screen could not be captured. Try again.');
    return new File([blob], `screen-${stamp()}.png`, { type: 'image/png' });
  } finally {
    stream.getTracks().forEach((t) => t.stop());
  }
}

// ---- Clipboard ------------------------------------------------------------- //
const PASTE_EXT = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif', 'image/bmp': 'bmp' };

/** The first image in a paste event as a File named pasted-YYYYMMDD-HHMMSS.<ext>, or null. */
export function imageFileFromPaste(event) {
  const items = Array.from(event.clipboardData?.items || []);
  const item = items.find((i) => i.kind === 'file' && i.type in PASTE_EXT);
  const file = item?.getAsFile();
  if (!file) return null;
  return new File([file], `pasted-${stamp()}.${PASTE_EXT[file.type]}`, { type: file.type });
}
