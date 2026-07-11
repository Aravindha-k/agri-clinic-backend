type SessionInvalidatedListener = (reason: 'session_conflict' | 'unauthorized') => void;

let listener: SessionInvalidatedListener | null = null;

export function setSessionInvalidatedListener(fn: SessionInvalidatedListener | null) {
  listener = fn;
}

export function notifySessionInvalidated(reason: 'session_conflict' | 'unauthorized') {
  listener?.(reason);
}
