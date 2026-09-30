import { useEffect, useRef, useState } from 'react';
import { GlobalWorkerOptions, type PDFDocumentProxy, type RenderTask, getDocument } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { documentPageUrl } from '../../api';
import { clampPage, nextZoom } from '../../lib/viewer';
import './DocumentViewer.css';

GlobalWorkerOptions.workerSrc = workerUrl;

export interface DocumentViewerProps {
  documentId: string;
  version: number;
  page?: number | null;
  title?: string;
  onClose?: () => void;
}

type Loaded = { url: string; doc: PDFDocumentProxy };
type Failure = { url: string; message: string };

export default function DocumentViewer({ documentId, version, page, title, onClose }: DocumentViewerProps) {
  const url = documentPageUrl(documentId, version, null);
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [current, setCurrent] = useState(page ?? 1);
  const [zoom, setZoom] = useState(1);

  // Follow the page the screen asks for (React's "adjust state when a prop changes" pattern, no effect needed).
  const target = `${url}#${page ?? 1}`;
  const [lastTarget, setLastTarget] = useState(target);
  if (target !== lastTarget) {
    setLastTarget(target);
    setCurrent(page ?? 1);
  }

  // Only ever render the document that belongs to the current URL, never the previous one mid-switch.
  const doc = loaded?.url === url ? loaded.doc : null;
  const error = failure?.url === url ? failure.message : null;
  const pageNumber = doc ? clampPage(current, doc.numPages) : 1;

  useEffect(() => {
    const task = getDocument({ url });
    let cancelled = false;
    task.promise
      .then((pdf) => {
        if (!cancelled) setLoaded({ url, doc: pdf });
      })
      .catch((e: unknown) => {
        if (!cancelled) setFailure({ url, message: e instanceof Error ? e.message : 'Could not open the PDF' });
      });
    return () => {
      cancelled = true;
      void task.destroy();
    };
  }, [url]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!doc || !canvas || !container) return;
    let cancelled = false;
    let render: RenderTask | null = null;
    doc.getPage(pageNumber).then((pdfPage) => {
      if (cancelled) return;
      // ponytail: fit-to-width is measured once per render; a window resize applies on the next page or zoom change
      const fit = (container.clientWidth - 32) / pdfPage.getViewport({ scale: 1 }).width;
      const viewport = pdfPage.getViewport({ scale: Math.max(fit, 0.1) * zoom });
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;
      render = pdfPage.render({ canvas, viewport, transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] });
      render.promise.catch(() => undefined); // a cancelled render rejects; nothing to report
    });
    return () => {
      cancelled = true;
      render?.cancel();
    };
  }, [doc, pageNumber, zoom]);

  return (
    <section className="doc-viewer" aria-label={title ? `${title}, page ${pageNumber}` : 'Document viewer'}>
      <header className="doc-viewer__toolbar">
        <span className="doc-viewer__title" title={title}>
          {title ?? 'Document'}
        </span>
        <div className="doc-viewer__controls">
          <button type="button" className="doc-viewer__btn" aria-label="Previous page" disabled={!doc || pageNumber <= 1} onClick={() => setCurrent(pageNumber - 1)}>
            ‹
          </button>
          <span className="doc-viewer__page mono">
            {doc ? `${pageNumber} / ${doc.numPages}` : '…'}
          </span>
          <button type="button" className="doc-viewer__btn" aria-label="Next page" disabled={!doc || pageNumber >= doc.numPages} onClick={() => setCurrent(pageNumber + 1)}>
            ›
          </button>
          <button type="button" className="doc-viewer__btn" aria-label="Zoom out" onClick={() => setZoom((z) => nextZoom(z, -1))}>
            −
          </button>
          <span className="doc-viewer__page mono">{Math.round(zoom * 100)}%</span>
          <button type="button" className="doc-viewer__btn" aria-label="Zoom in" onClick={() => setZoom((z) => nextZoom(z, 1))}>
            +
          </button>
          <a className="doc-viewer__link" href={documentPageUrl(documentId, version, pageNumber)} target="_blank" rel="noreferrer">
            New tab ↗
          </a>
          {onClose && (
            <button type="button" className="doc-viewer__btn doc-viewer__close" aria-label="Close viewer" onClick={onClose}>
              ✕
            </button>
          )}
        </div>
      </header>
      <div className="doc-viewer__canvas-wrap" ref={containerRef}>
        {error ? (
          <p className="doc-viewer__message" role="alert">
            {error}
          </p>
        ) : (
          <>
            {!doc && <p className="doc-viewer__message">Loading document…</p>}
            <canvas ref={canvasRef} className="doc-viewer__canvas" hidden={!doc} />
          </>
        )}
      </div>
    </section>
  );
}
