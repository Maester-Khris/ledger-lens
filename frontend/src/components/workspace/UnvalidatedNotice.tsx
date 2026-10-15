import { Link } from 'react-router';
import type { UnvalidatedDto } from '../../api';

interface UnvalidatedNoticeProps {
  notice: UnvalidatedDto;
}

export function UnvalidatedNotice({ notice }: UnvalidatedNoticeProps) {
  return (
    <div className="ws-notice" role="note">
      <strong>Not confirmed, awaiting review</strong> in {notice.title}:{' '}
      {notice.fields.map((f) => f.label).join(', ')}.{' '}
      <Link to="/review">See the anomaly queue →</Link>
    </div>
  );
}
