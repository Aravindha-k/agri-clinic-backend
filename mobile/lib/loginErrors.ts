/**
 * Canonical mobile login error normalization.
 * Preserves backend status/code/fields; never maps HTTP responses to "no internet".
 */

export type LoginError =
  | { type: 'network'; message: string }
  | { type: 'timeout'; message: string }
  | { type: 'invalid_credentials'; message: string }
  | { type: 'account_inactive'; message: string }
  | { type: 'login_disabled'; message: string }
  | { type: 'profile_missing'; message: string }
  | { type: 'session_conflict'; message: string }
  | {
      type: 'validation';
      message: string;
      fields?: Record<string, string[]>;
    }
  | { type: 'server'; message: string }
  | { type: 'unknown'; message: string; status?: number; code?: string };

const MSG = {
  network: 'Unable to connect. Check your internet connection and try again.',
  timeout: 'The request timed out. Please try again.',
  invalid: 'Incorrect username or password.',
  inactive: 'Your account is inactive. Please contact the administrator.',
  disabled: 'Mobile login is disabled for this account. Please contact the administrator.',
  profile: 'Your employee profile is incomplete. Please contact the administrator.',
  session: 'Your login session is no longer valid on this device. Please sign in again.',
  server: 'Something went wrong on the server. Please try again shortly.',
  validation: 'Please check the login details and try again.',
} as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function asStringArray(value: unknown): string[] | undefined {
  if (Array.isArray(value)) {
    return value.map((v) => String(v));
  }
  if (typeof value === 'string' && value) {
    return [value];
  }
  return undefined;
}

export function extractLoginErrorFields(errors: unknown): Record<string, string[]> | undefined {
  if (!isRecord(errors)) return undefined;
  const out: Record<string, string[]> = {};
  for (const [key, value] of Object.entries(errors)) {
    if (key === 'detail' || key === 'non_field_errors') continue;
    const arr = asStringArray(value);
    if (arr?.length) out[key] = arr;
  }
  return Object.keys(out).length ? out : undefined;
}

export type LoginFailureInput = {
  status?: number;
  code?: string;
  message?: string;
  errors?: unknown;
  networkError?: boolean;
  timeout?: boolean;
};

export function normalizeLoginError(input: LoginFailureInput): LoginError {
  if (input.timeout) {
    return { type: 'timeout', message: MSG.timeout };
  }
  if (input.networkError || input.status === 0 || input.status == null) {
    return { type: 'network', message: MSG.network };
  }

  const code = (input.code || '').toUpperCase();
  const status = input.status ?? 0;
  const backendMessage = (input.message || '').trim();

  if (
    status === 409 ||
    code === 'SESSION_REPLACED' ||
    code === 'DEVICE_SESSION_CONFLICT' ||
    backendMessage.toLowerCase().includes('another device')
  ) {
    return { type: 'session_conflict', message: MSG.session };
  }

  if (
    code === 'LOGIN_DISABLED' ||
    backendMessage.toLowerCase().includes('mobile login is disabled')
  ) {
    return { type: 'login_disabled', message: MSG.disabled };
  }

  if (
    code === 'ACCOUNT_INACTIVE' ||
    code === 'ACCOUNT_DISABLED' ||
    backendMessage.toLowerCase().includes('account is inactive') ||
    backendMessage.toLowerCase().includes('account is currently disabled') ||
    backendMessage.toLowerCase().includes('account is disabled')
  ) {
    return { type: 'account_inactive', message: MSG.inactive };
  }

  if (
    code === 'EMPLOYEE_PROFILE_MISSING' ||
    backendMessage.toLowerCase().includes('employee profile')
  ) {
    return { type: 'profile_missing', message: MSG.profile };
  }

  if (
    status === 401 ||
    code === 'INVALID_CREDENTIALS' ||
    code === 'UNAUTHORIZED' ||
    backendMessage.toLowerCase().includes('invalid credentials') ||
    backendMessage.toLowerCase().includes('incorrect username or password') ||
    backendMessage.toLowerCase().includes('no active account')
  ) {
    return { type: 'invalid_credentials', message: MSG.invalid };
  }

  if (status === 400 || code === 'VALIDATION_ERROR' || code === 'BAD_REQUEST') {
    const fields = extractLoginErrorFields(input.errors);
    const firstFieldMsg = fields
      ? Object.values(fields).flat().find(Boolean)
      : undefined;
    return {
      type: 'validation',
      message: firstFieldMsg || backendMessage || MSG.validation,
      fields,
    };
  }

  if (status >= 500) {
    return { type: 'server', message: MSG.server };
  }

  return {
    type: 'unknown',
    message: backendMessage || MSG.server,
    status,
    code: input.code,
  };
}

export function loginErrorMessage(error: LoginError): string {
  return error.message;
}
