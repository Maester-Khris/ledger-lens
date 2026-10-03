import { useState, type FormEvent } from 'react';
import { type FeedbackRating, sendFeedback } from '../api';
import { ThumbDownIcon, ThumbUpIcon } from './Icons';
import './FeedbackControl.css';

const MAX_COMMENT_LENGTH = 1000; // same cap as the API

interface FeedbackControlProps {
  turnId: string;
}

type Status = 'idle' | 'saving' | 'saved' | 'comment-saved' | 'failed';

const MESSAGES: Partial<Record<Status, string>> = {
  saved: 'Feedback saved',
  'comment-saved': 'Comment saved',
  failed: "Couldn't save your feedback. Try again.",
};

/** Thumbs under a reply. A click saves at once; a comment or the other thumb saves a new row, and the latest wins. */
export function FeedbackControl({ turnId }: FeedbackControlProps) {
  const [rating, setRating] = useState<FeedbackRating | null>(null);
  const [comment, setComment] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const saving = status === 'saving';

  const save = async (next: FeedbackRating, text?: string) => {
    setStatus('saving');
    try {
      await sendFeedback(turnId, next, text);
      setRating(next);
      if (text) setComment('');
      setStatus(text ? 'comment-saved' : 'saved');
    } catch {
      setStatus('failed');
    }
  };

  const submitComment = (event: FormEvent) => {
    event.preventDefault();
    if (rating && comment.trim()) void save(rating, comment.trim());
  };

  return (
    <div className="feedback">
      <div className="feedback__row">
        <span className="feedback__label">Was this helpful?</span>
        <button type="button" className="feedback__thumb" aria-label="Good answer" aria-pressed={rating === 'up'} disabled={saving} onClick={() => void save('up')}>
          <ThumbUpIcon size={15} />
        </button>
        <button type="button" className="feedback__thumb" aria-label="Bad answer" aria-pressed={rating === 'down'} disabled={saving} onClick={() => void save('down')}>
          <ThumbDownIcon size={15} />
        </button>
        <span className={`feedback__status${status === 'failed' ? ' feedback__status--failed' : ''}`} role="status">
          {MESSAGES[status] ?? ''}
        </span>
      </div>
      {rating && (
        <form className="feedback__comment" onSubmit={submitComment}>
          <input
            type="text"
            className="feedback__input"
            aria-label="Add a comment (optional)"
            placeholder="Add a comment (optional)"
            maxLength={MAX_COMMENT_LENGTH}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
          />
          <button type="submit" className="btn btn-secondary feedback__send" disabled={saving || !comment.trim()}>
            Send comment
          </button>
        </form>
      )}
    </div>
  );
}
