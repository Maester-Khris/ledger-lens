import { useEffect, useRef, useState } from 'react';
import { documentPageUrl } from '../api';
import { renderPdfPage } from '../lib/pdf';
import './DocumentViewer.css';

export interface DocumentViewerProps {
  documentId: string;
  version: number;
  pageCount: number;
  onClose: () => void;
}

export default function DocumentViewer({ documentId, version, pageCount, onClose }: DocumentViewerProps) {
  const [page, setPage] = useState(1);
  const [error, setError] = useState<Error | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let abort = false;
    const url = documentPageUrl(documentId, version, null);

    renderPdfPage(url, page, canvas).catch((err) => {
      if (!abort) setError(err);
    });

    return () => {
      abort = true;
    };
  }, [documentId, version, page]);

  return (
    <div className="viewer-overlay" onClick={onClose}>
      <div className="viewer" onClick={(e) => e.stopPropagation()}>
        <div className="viewer__header">
          <div className="viewer__controls">
            <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Prev</button>
            <span>Page {page} of {pageCount}</span>
            <button disabled={page >= pageCount} onClick={() => setPage(p => p + 1)}>Next</button>
          </div>
          <button className="viewer__close" onClick={onClose}>Close</button>
        </div>
        <div className="viewer__content">
          {error ? (
            <div className="viewer__error">Failed to load PDF: {error.message}</div>
          ) : (
            <canvas ref={canvasRef} className="viewer__canvas" />
          )}
        </div>
      </div>
    </div>
  );
}
