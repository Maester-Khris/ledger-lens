import { lazy } from 'react';

export type { DocumentViewerProps } from './DocumentViewer';

// Code-split: pdf.js and its worker are fetched only by screens that actually render a document.
export const DocumentViewer = lazy(() => import('./DocumentViewer'));
