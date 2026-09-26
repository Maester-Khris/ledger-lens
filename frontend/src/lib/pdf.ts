import * as pdfjsLib from 'pdfjs-dist';

// pdfjs-dist needs a worker. In Vite, ?url imports the asset path.
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

export type PageSize = { w: number; h: number };

export function scaleToFit(page: PageSize, container: PageSize): number {
  return Math.min(container.w / page.w, container.h / page.h);
}

export async function renderPdfPage(url: string, pageNumber: number, canvas: HTMLCanvasElement): Promise<void> {
  const doc = await pdfjsLib.getDocument({ url }).promise;
  const page = await doc.getPage(pageNumber);
  
  // High-DPI support: render at double resolution and scale down in CSS
  const unscaled = page.getViewport({ scale: 1.0 });
  const scale = scaleToFit({ w: unscaled.width, h: unscaled.height }, { w: canvas.clientWidth, h: canvas.clientHeight });
  const viewport = page.getViewport({ scale: scale * 2 });
  
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  
  const ctx = canvas.getContext('2d', { alpha: false });
  if (!ctx) throw new Error('Canvas 2D context unavailable');
  
  // The plan allows `as any` if pdfjs-dist parameter types reject this dict
  await page.render({ canvasContext: ctx, viewport } as any).promise;
  await doc.cleanup();
}
