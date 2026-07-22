import { API_BASE_URL } from '@/lib/config';
import {
  getAccessToken,
  getRefreshToken,
  getDeviceSessionId,
  saveTokens,
  saveAuthSession,
  clearTokens,
} from '@/lib/authStorage';
import { notifySessionInvalidated } from '@/lib/authEvents';
import { appLog } from '@/lib/logger';
import {
  loginErrorMessage,
  normalizeLoginError,
  type LoginError,
} from '@/lib/loginErrors';

const DEVICE_SESSION_HEADER = 'X-Device-Session';

const SESSION_INVALID_MESSAGE =
  'Your login session is no longer valid on this device. Please sign in again.';

export type ApiErrorOptions = {
  code?: string;
  requiresReauth?: boolean;
  retryable?: boolean;
  validationErrors?: unknown;
  diagnosticMessage?: string;
  loginError?: LoginError;
};

export class ApiError extends Error {
  status: number;
  body?: unknown;
  code?: string;
  requiresReauth: boolean;
  retryable: boolean;
  validationErrors?: unknown;
  diagnosticMessage?: string;
  loginError?: LoginError;

  constructor(message: string, status: number, body?: unknown, options: ApiErrorOptions = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
    this.code = options.code;
    this.requiresReauth = options.requiresReauth ?? false;
    this.retryable = options.retryable ?? (status >= 500 || status === 408 || status === 429);
    this.validationErrors = options.validationErrors;
    this.diagnosticMessage = options.diagnosticMessage;
    this.loginError = options.loginError;
  }
}

export type PaginatedResult<T> = {
  results: T[];
  count: number;
  next: string | null;
  previous: string | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function extractErrorEnvelope(parsed: unknown): {
  message?: string;
  code?: string;
  errors?: unknown;
} {
  if (!isRecord(parsed)) return {};
  const message =
    typeof parsed.message === 'string'
      ? parsed.message
      : typeof parsed.detail === 'string'
        ? parsed.detail
        : undefined;
  const code = typeof parsed.code === 'string' ? parsed.code : undefined;
  const errors = parsed.errors ?? parsed.error;
  return { message, code, errors };
}

function userMessageForStatus(
  status: number,
  code: string | undefined,
  backendMessage: string | undefined,
  options: { skipAuth?: boolean } = {},
): { message: string; requiresReauth: boolean } {
  const skipAuth = Boolean(options.skipAuth);
  if (
    status === 409 ||
    code === 'SESSION_REPLACED' ||
    (backendMessage || '').toLowerCase().includes('another device')
  ) {
    return { message: SESSION_INVALID_MESSAGE, requiresReauth: true };
  }
  // Login / anonymous requests: 401 means bad credentials, not an expired session.
  if (status === 401 && skipAuth) {
    return {
      message: backendMessage || 'Incorrect username or password.',
      requiresReauth: false,
    };
  }
  if (status === 401) {
    return {
      message: 'Your session expired. Please sign in again.',
      requiresReauth: true,
    };
  }
  if (status === 403) {
    return {
      message: backendMessage || 'You do not have permission to do that.',
      requiresReauth: false,
    };
  }
  if (status === 400) {
    return {
      message: backendMessage || 'Please check the form and try again.',
      requiresReauth: false,
    };
  }
  if (status >= 500) {
    return {
      message: 'Server is temporarily unavailable. Please try again shortly.',
      requiresReauth: false,
    };
  }
  if (!backendMessage || backendMessage.length > 180) {
    return { message: 'Something went wrong. Please try again.', requiresReauth: false };
  }
  return { message: backendMessage, requiresReauth: false };
}

async function refreshAccess(): Promise<string | null> {
  const refresh = await getRefreshToken();
  if (!refresh) return null;
  const sessionId = await getDeviceSessionId();
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (sessionId) {
    headers[DEVICE_SESSION_HEADER] = sessionId;
  }
  const body: { refresh: string; device_session_id?: string } = { refresh };
  if (sessionId) {
    body.device_session_id = sessionId;
  }
  const res = await fetch(`${API_BASE_URL}/mobile/auth/refresh/`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    appLog.warn('auth.refresh_failed', { status: res.status });
    await clearTokens();
    notifySessionInvalidated(
      res.status === 409 ? 'session_conflict' : 'unauthorized',
    );
    return null;
  }
  const data = (await res.json()) as {
    access?: string;
    refresh?: string;
    device_session_id?: string;
  };
  if (!data.access) {
    await clearTokens();
    notifySessionInvalidated('unauthorized');
    return null;
  }
  const nextRefresh = data.refresh || refresh;
  const nextSession = data.device_session_id || sessionId;
  if (nextSession) {
    await saveAuthSession({
      access: data.access,
      refresh: nextRefresh,
      deviceSessionId: String(nextSession),
    });
  } else {
    await saveTokens(data.access, nextRefresh);
  }
  appLog.info('auth.refresh_ok');
  return data.access;
}

export type RequestOptions = Omit<RequestInit, 'body'> & {
  token?: string | null;
  json?: unknown;
  formData?: FormData;
  skipAuth?: boolean;
};

export async function apiRequest<T = unknown>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { token: tokenOverride, json, formData, skipAuth, headers, ...rest } = options;
  let token = tokenOverride ?? (skipAuth ? null : await getAccessToken());
  const deviceSessionId = skipAuth ? null : await getDeviceSessionId();

  const url = path.startsWith('http')
    ? path
    : `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
  const pathForLog = path.startsWith('http') ? path.replace(API_BASE_URL, '') : path;

  const exec = async (bearer: string | null): Promise<Response> => {
    const h = new Headers(headers);
    if (bearer) h.set('Authorization', `Bearer ${bearer}`);
    if (deviceSessionId) h.set(DEVICE_SESSION_HEADER, deviceSessionId);
    const body: BodyInit | undefined = formData
      ? formData
      : json !== undefined
        ? JSON.stringify(json)
        : undefined;
    if (body !== undefined && !formData && !h.has('Content-Type')) {
      h.set('Content-Type', 'application/json');
    }
    return fetch(url, {
      ...rest,
      headers: h,
      body,
    });
  };

  let res: Response;
  try {
    res = await exec(token);
    if (res.status === 401 && !skipAuth) {
      const next = await refreshAccess();
      if (next) {
        token = next;
        res = await exec(next);
      }
    }
  } catch (err) {
    const raw = err instanceof Error ? err.message : String(err);
    const isTimeout =
      /timeout|timed out|abort/i.test(raw) ||
      (err instanceof Error && err.name === 'AbortError');
    const isNetwork =
      isTimeout ||
      /network request failed|failed to fetch|networkerror|internet|offline|unreachable/i.test(
        raw,
      );
    appLog.error('api.transport_failed', {
      path: pathForLog,
      method: String(rest.method || 'GET'),
      isTimeout,
      isNetwork,
    });
    const loginError = normalizeLoginError({
      networkError: isNetwork && !isTimeout,
      timeout: isTimeout,
    });
    throw new ApiError(loginErrorMessage(loginError), 0, { transport: raw }, {
      code: isTimeout ? 'TIMEOUT' : 'NETWORK_ERROR',
      requiresReauth: false,
      retryable: true,
      loginError,
      diagnosticMessage: raw,
    });
  }

  const text = await res.text();
  let parsed: unknown = text;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = text;
  }

  if (!res.ok) {
    const envelope = extractErrorEnvelope(parsed);
    const mapped = userMessageForStatus(res.status, envelope.code, envelope.message, {
      skipAuth: Boolean(skipAuth),
    });
    appLog.error('api.request_failed', {
      path: pathForLog,
      status: res.status,
      code: envelope.code ?? null,
      method: String(rest.method || 'GET'),
    });

    if (mapped.requiresReauth && !skipAuth) {
      // Do not retry 409; clear auth so the next UI frame returns to login.
      if (res.status === 409 || envelope.code === 'SESSION_REPLACED') {
        await clearTokens();
        notifySessionInvalidated('session_conflict');
      } else if (res.status === 401) {
        await clearTokens();
        notifySessionInvalidated('unauthorized');
      }
    }

    const loginError = skipAuth
      ? normalizeLoginError({
          status: res.status,
          code: envelope.code,
          message: envelope.message,
          errors: envelope.errors,
        })
      : undefined;

    throw new ApiError(
      loginError ? loginErrorMessage(loginError) : mapped.message,
      res.status,
      parsed,
      {
        code: envelope.code,
        requiresReauth: mapped.requiresReauth,
        retryable: res.status >= 500 || res.status === 408 || res.status === 429,
        validationErrors: envelope.errors,
        diagnosticMessage: envelope.message,
        loginError,
      },
    );
  }

  return parsed as T;
}

/** Unwrap `{ success, data }` envelopes used by most agri APIs. */
export function unwrapData<T>(body: unknown): T {
  if (
    isRecord(body) &&
    body.success === true &&
    'data' in body
  ) {
    return body.data as T;
  }
  return body as T;
}

/**
 * Normalize paginated farmer/visit-style responses into one shape.
 * Accepts confirmed backend variants:
 * - `{ success, data: { count, next, previous, results } }`
 * - `{ count, next, previous, results }`
 * - bare array (masters without pagination)
 */
export function normalizePaginated<T>(body: unknown): PaginatedResult<T> {
  const empty: PaginatedResult<T> = {
    results: [],
    count: 0,
    next: null,
    previous: null,
  };

  const candidate = unwrapData<unknown>(body);

  if (Array.isArray(candidate)) {
    return {
      results: candidate as T[],
      count: candidate.length,
      next: null,
      previous: null,
    };
  }

  if (isRecord(candidate) && Array.isArray(candidate.results)) {
    const results = candidate.results as T[];
    return {
      results,
      count: typeof candidate.count === 'number' ? candidate.count : results.length,
      next: typeof candidate.next === 'string' ? candidate.next : null,
      previous: typeof candidate.previous === 'string' ? candidate.previous : null,
    };
  }

  // Rare: results nested under data without success flag already unwrapped above
  if (isRecord(body) && isRecord(body.data) && Array.isArray(body.data.results)) {
    const results = body.data.results as T[];
    return {
      results,
      count: typeof body.data.count === 'number' ? body.data.count : results.length,
      next: typeof body.data.next === 'string' ? body.data.next : null,
      previous: typeof body.data.previous === 'string' ? body.data.previous : null,
    };
  }

  return empty;
}

function normalizeList<T extends { id: number }>(body: unknown): T[] {
  const page = normalizePaginated<T>(body);
  if (page.results.length) return page.results;
  const data = unwrapData<unknown>(body);
  if (Array.isArray(data)) return data as T[];
  return [];
}

export type MobileLoginResponse = {
  access: string;
  refresh: string;
  device_session_id: string;
  active_device_id?: string;
  session_version?: number;
  user: Record<string, unknown>;
};

/** Login — top-level JWT payload including device_session_id (not success-wrapped). */
export async function mobileLogin(body: {
  employee_id: string;
  password: string;
  platform?: string;
  device_name?: string;
}) {
  appLog.info('auth.login_start');
  const res = await apiRequest<MobileLoginResponse>('/mobile/auth/login/', {
    method: 'POST',
    json: body,
    skipAuth: true,
  });
  if (!res.access || !res.refresh || !res.device_session_id) {
    appLog.error('auth.login_incomplete_response', {
      hasAccess: Boolean(res.access),
      hasRefresh: Boolean(res.refresh),
      hasSession: Boolean(res.device_session_id),
    });
    throw new ApiError('Login response was incomplete. Please try again.', 500, res);
  }
  appLog.info('auth.login_ok', {
    userId: typeof res.user?.id === 'number' ? res.user.id : undefined,
  });
  return res;
}

export type DashboardData = {
  today_visits: number;
  completed_visits: number;
  pending_visits: number;
  active_visit: VisitDto | null;
  visits_today?: number;
  farmers_covered?: number;
  work_status?: string;
};

export type VisitDto = {
  id: number;
  status?: string | null;
  visit_date?: string | null;
  visit_time?: string | null;
  village_name?: string | null;
  district_name?: string | null;
  farmer_name?: string | null;
  farmer_phone?: string | null;
  farmer?: { id: number | null; name?: string; phone?: string } | null;
  farmer_info?: { id: number | null; name?: string; phone?: string } | null;
  field_info?: { id: number | null; land_name?: string; land_size?: string | null } | null;
  crop_info?: { id?: number; name?: string; name_en?: string; name_ta?: string } | null;
  crop?: number | null;
  latitude?: number | null;
  longitude?: number | null;
  notes?: string | null;
  pest_issue?: boolean | null;
  disease_issue?: boolean | null;
  land_name?: string | null;
};

export type VisitDetailDto = {
  id: number;
  status?: string | null;
  visit_date?: string | null;
  visit_time?: string | null;
  farmer_name?: string | null;
  farmer_phone?: string | null;
  farmer?: { id: number; name?: string; phone?: string; farmer_code?: string } | null;
  field?: { id: number; land_name?: string; land_size?: unknown; gps_location?: string } | null;
  village_name?: string | null;
  district_name?: string | null;
  crop_name?: string | null;
  crop_stage?: string | null;
  crop_health?: string | null;
  pest_issue?: boolean | null;
  disease_issue?: boolean | null;
  weed_condition?: string | null;
  land_name?: string | null;
  land_area?: number | null;
  notes?: string | null;
  fertilizer_advice?: string | null;
  pesticide_advice?: string | null;
  irrigation_advice?: string | null;
  general_advice?: string | null;
  follow_up_required?: boolean | null;
  next_visit_date?: string | null;
  latitude?: number | null;
  longitude?: number | null;
};

export type CreateVisitPayload = {
  farmer_id: number;
  crop: number;
  latitude: number;
  longitude: number;
  notes?: string;
  pest_issue?: boolean;
  disease_issue?: boolean;
  field?: number;
};

export async function fetchDashboard(token: string | null) {
  const raw = await apiRequest<unknown>('/mobile/dashboard/', { token });
  return unwrapData<DashboardData>(raw);
}

export async function fetchWorkStatus(token: string | null) {
  const raw = await apiRequest<unknown>('/mobile/work/status/', { token });
  return unwrapData<{ work_status: 'started' | 'not_started' | 'stopped' | 'expired' }>(raw);
}

export async function startWork(
  token: string | null,
  coords: { latitude?: number; longitude?: number } | undefined,
) {
  const raw = await apiRequest<unknown>('/mobile/work/start/', {
    method: 'POST',
    token,
    json: coords && coords.latitude != null ? coords : {},
  });
  return unwrapData<Record<string, unknown>>(raw);
}

export async function stopWork(token: string | null) {
  const raw = await apiRequest<unknown>('/mobile/work/stop/', { method: 'POST', token, json: {} });
  return unwrapData<Record<string, unknown>>(raw);
}

export async function pingTracking(
  token: string | null,
  payload: { latitude: number; longitude: number; accuracy?: number | null },
) {
  const raw = await apiRequest<unknown>('/mobile/tracking/', {
    method: 'POST',
    token,
    json: {
      latitude: payload.latitude,
      longitude: payload.longitude,
      accuracy: payload.accuracy ?? undefined,
    },
  });
  return unwrapData<{ location_id?: number }>(raw);
}

export async function fetchVisitStats(token: string | null) {
  const raw = await apiRequest<unknown>('/mobile/visits/stats/', { token });
  return unwrapData<{
    today_visits: number;
    completed: number;
    pending: number;
  }>(raw);
}

export async function fetchMyVisits(
  token: string | null,
  dateFilter?: 'today' | 'week' | 'month' | 'all',
) {
  const qs =
    dateFilter && dateFilter !== 'all' ? `?date_filter=${encodeURIComponent(dateFilter)}` : '';
  const raw = await apiRequest<unknown>(`/mobile/visits/${qs}`, { token });
  return normalizePaginated<VisitDto>(raw).results;
}

export async function createVisit(token: string | null, body: CreateVisitPayload) {
  appLog.info('visit.create_start', {
    farmerId: body.farmer_id,
    cropId: body.crop,
    hasGps: body.latitude != null && body.longitude != null,
  });
  const raw = await apiRequest<unknown>('/mobile/visits/', {
    method: 'POST',
    token,
    json: body,
  });
  const data = unwrapData<{ visit_id?: number; duplicate?: boolean }>(raw);
  appLog.info('visit.create_ok', {
    visitId: data.visit_id ?? null,
    duplicate: data.duplicate ?? false,
  });
  return data;
}

export async function fetchVisitDetail(token: string | null, id: number) {
  const raw = await apiRequest<unknown>(`/visits/${id}/`, { token });
  if (isRecord(raw) && raw.success === false) {
    throw new ApiError('Visit not found', 404, raw);
  }
  // VisitDetailUpdateAPI returns a raw object (not success-wrapped).
  const data = unwrapData<VisitDetailDto>(raw);
  return data;
}

export async function patchVisit(
  token: string | null,
  id: number,
  body: Record<string, unknown>,
) {
  return apiRequest<unknown>(`/visits/${id}/`, { method: 'PATCH', token, json: body });
}

export async function completeVisit(
  token: string | null,
  id: number,
  body: { notes?: string; latitude?: number; longitude?: number },
) {
  const raw = await apiRequest<unknown>(`/visits/${id}/complete/`, {
    method: 'POST',
    token,
    json: body,
  });
  return raw;
}

export type FarmerListItem = {
  id: number;
  farmer_code?: string;
  name: string;
  phone: string;
  village_name?: string;
  district_name?: string;
  village?: number | null;
  district?: number | null;
  fields?: unknown[];
  address?: string;
};

export async function fetchFarmersPage(
  token: string | null,
  page: number,
  search: string,
  pageSize = 50,
) {
  const q = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (search.trim()) q.set('search', search.trim());
  appLog.info('farmers.list_start', { page, hasSearch: Boolean(search.trim()), pageSize });
  const raw = await apiRequest<unknown>(`/mobile/farmers/?${q.toString()}`, { token });
  const normalized = normalizePaginated<FarmerListItem>(raw);
  appLog.info('farmers.list_ok', { count: normalized.count, pageSize: normalized.results.length });
  return normalized;
}

export async function fetchFarmerDetail(token: string | null, id: number) {
  const raw = await apiRequest<unknown>(`/mobile/farmers/${id}/`, { token });
  return unwrapData<Record<string, unknown>>(raw);
}

export async function fetchFarmerVisitsPage(token: string | null, farmerId: number, page: number) {
  const raw = await apiRequest<unknown>(`/farmers/${farmerId}/visits/?page=${page}`, { token });
  return normalizePaginated<VisitDto>(raw);
}

export async function fetchFarmerActivityPage(
  token: string | null,
  farmerId: number,
  page: number,
) {
  const raw = await apiRequest<unknown>(`/farmers/${farmerId}/activity/?page=${page}`, {
    token,
  });
  return normalizePaginated<Record<string, unknown>>(raw);
}

export async function createFarmer(
  token: string | null,
  body: {
    name: string;
    phone: string;
    district?: number | null;
    village?: number | null;
    address?: string;
  },
) {
  const raw = await apiRequest<unknown>('/farmers/', { method: 'POST', token, json: body });
  return unwrapData<FarmerListItem>(raw);
}

export type MasterDistrict = { id: number; name: string };
export type MasterVillage = { id: number; name: string; district?: number };
export type MasterCrop = { id: number; name_en?: string; name_ta?: string };

export async function fetchDistricts(token: string | null) {
  const raw = await apiRequest<unknown>('/masters/districts/?page_size=500', { token });
  return normalizeList<MasterDistrict>(raw);
}

export async function fetchVillages(token: string | null, districtId: number) {
  const raw = await apiRequest<unknown>(
    `/masters/villages/?district=${districtId}&page_size=500`,
    { token },
  );
  return normalizeList<MasterVillage>(raw);
}

export async function fetchCropsCatalog(token: string | null) {
  const raw = await apiRequest<unknown>('/masters/crops/', { token });
  return normalizeList<MasterCrop>(raw);
}

export type ProfileData = {
  id: number;
  username: string;
  employee_id: string;
  phone?: string;
  is_active_employee?: boolean;
};

export async function fetchProfile(token: string | null) {
  const raw = await apiRequest<unknown>('/mobile/auth/me/', { token });
  return unwrapData<ProfileData>(raw);
}
