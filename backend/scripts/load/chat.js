// N3: the chat path under rising concurrency (MediCoord Test B, adapted). One iteration is one fresh guest holding one
// conversation of TURNS turns on the same chat session, reading each reply for 1 s. Meant for a local API that uses
// the provider mock and the stub index (scripts/load/README.md); against real OpenAI every turn is billed.
//
//   BASE_URL    API under test (default http://127.0.0.1:8012)
//   STEPS       concurrent conversations per level (default 5,10,20,40,80,160)
//   STEP_HOLD   how long each level is held (default 1m)
//   TURNS       turns per conversation (default 2)
//
// Turn time is the whole streamed reply; time to first byte is k6's `waiting`. The final SSE event decides the
// outcome: answer, refused or clarify count as served; error, a non-200 or a missing final event count as failed.
// X3: a 503 with problem type /problems/busy is busy (the server shed the turn), not failed; every other 503 (nginx's
// own, when a replica is gone) is a failure. Each failure carries a `kind` tag (guest, cut, timeout, http_<status>,
// error_event) and served turns an `upstream` tag (X-Upstream, behind nginx) for the replica-loss run.
//
//   NO_ABORT    1 = run the whole ladder even past the stop rule (to measure overload, not stop at it)
import http from 'k6/http';
import { sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';
import { SharedArray } from 'k6/data';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8012';
const STEPS = (__ENV.STEPS || '5,10,20,40,80,160').split(',').map((s) => Number(s.trim()));
const STEP_HOLD = __ENV.STEP_HOLD || '1m';
const TURNS = Number(__ENV.TURNS || 2);

const questions = new SharedArray('golden answerable questions', () => JSON.parse(open('./questions.json')));
const turnDuration = new Trend('chat_turn_duration', true);
const turnFirstByte = new Trend('chat_turn_first_byte', true);
const turnFailed = new Rate('chat_turn_failed');
const turnBusy = new Rate('chat_turn_busy');
const busyDuration = new Trend('chat_busy_duration', true);
const turnTimeout = new Rate('chat_turn_timeout');
const turnsCut = new Counter('chat_turns_cut');
const turnsServed = new Counter('chat_turns_served');
const turnsAnswered = new Counter('chat_turns_answered');

export const options = {
  scenarios: {
    chat: {
      executor: 'ramping-vus',
      startVUs: 0,
      gracefulRampDown: '30s',
      stages: STEPS.flatMap((level) => [{ target: level, duration: '10s' }, { target: level, duration: STEP_HOLD }]),
    },
  },
  // Our own stop rule (an assumption, same as MediCoord): past p95 15 s or 5% failed, the curve has bent.
  thresholds: {
    chat_turn_duration: [{ threshold: 'p(95)<15000', abortOnFail: !__ENV.NO_ABORT, delayAbortEval: STEP_HOLD }],
    chat_turn_failed: [{ threshold: 'rate<0.05', abortOnFail: !__ENV.NO_ABORT, delayAbortEval: STEP_HOLD }],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

function isBusy(response) {
  if (response.status !== 503) return false;
  try {
    return JSON.parse(response.body).type === '/problems/busy';
  } catch (e) {
    return false;
  }
}

function failureKind(response, outcome) {
  if (response.timings.duration >= 55000) return 'timeout';
  // Behind nginx a replica that dies mid-stream drops the connection (status 0, no headers); direct, the 200 just ends.
  if (response.status === 0 || (response.status === 200 && outcome === null)) return 'cut';
  if (response.status === 200) return 'error_event';
  return `http_${response.status}`;
}

function finalEvent(body) {
  const events = (body || '').match(/^event: (\w+)$/gm) || [];
  return events.length ? events[events.length - 1].slice(7) : null;
}

export default function () {
  const guest = http.post(`${BASE_URL}/guests`, null, { tags: { name: 'guest' } });
  if (guest.status !== 201) {
    turnFailed.add(true, { kind: 'guest' });
    sleep(1);
    return;
  }
  const headers = { 'Content-Type': 'application/json', 'X-Guest-Id': guest.json('id') };
  const sessionId = `load-${__VU}-${__ITER}-${Date.now()}`;
  for (let i = 0; i < TURNS; i++) {
    const message = questions[Math.floor(Math.random() * questions.length)];
    const turn = http.post(`${BASE_URL}/chat`, JSON.stringify({ session_id: sessionId, message }),
      { headers, tags: { name: 'chat' }, timeout: '120s' });
    const busy = turn.status === 429 || isBusy(turn);
    const outcome = turn.status === 200 ? finalEvent(turn.body) : null;
    const served = ['answer', 'refused', 'clarify'].includes(outcome);
    const upstream = turn.headers['X-Upstream'] || 'direct';
    turnBusy.add(busy);
    if (busy) busyDuration.add(turn.timings.duration);
    if (!served && !busy) {
      const kind = failureKind(turn, outcome);
      turnFailed.add(true, { kind, upstream });
      turnTimeout.add(kind === 'timeout');
      if (kind === 'cut') turnsCut.add(1, { upstream });
    } else {
      turnFailed.add(false);
      turnTimeout.add(false);
    }
    if (served) {
      turnDuration.add(turn.timings.duration, { upstream });
      turnFirstByte.add(turn.timings.waiting);
      turnsServed.add(1, { upstream });
      if (outcome === 'answer') turnsAnswered.add(1);
    } else {
      // busy or failed: the conversation ends here, as a guest would give up. A busy guest first waits the
      // Retry-After it was given, so a refused virtual user does not loop on POST /guests and add load of its own.
      if (busy) sleep(Number(turn.headers['Retry-After'] || 3));
      break;
    }
    sleep(1); // a person reads the reply before asking again
  }
}
