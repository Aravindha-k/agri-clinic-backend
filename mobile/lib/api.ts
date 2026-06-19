import { API_BASE_URL } from '@/lib/config';
import {
  getAccessToken,
  getRefreshToken,
  saveTokens,
  clearTokens,
} from '@/lib/authStorage';

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public body?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function refreshAccess(): Promise<string | null> {
  const refresh = await getRefreshToken();
  if (!refresh) return null;
  const res = await fetch(`${API_BASE_URL}/mobile/auth/refresh/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh }),
  });
  if (!res.ok) {
    await clearTokens();
    return null;
  }
  const data = (await res.json()) as { access?: string };
  if (!data.access) {
    await clearTokens();
    return null;
  }
  await saveTokens(data.access, refresh);
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

  const url = path.startsWith('http') ? path : `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;

  const exec = async (bearer: string | null): Promise<Response> => {
    const h = new Headers(headers);
    if (bearer) h.set('Authorization', `Bearer ${bearer}`);
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

  let res = await exec(token);
  if (res.status === 401 && !skipAuth) {
    const next = await refreshAccess();
    if (next) {
      token = next;
      res = await exec(next);
    }
  }

  const text = await res.text();
  let parsed: unknown = text;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = text;
  }

  if (!res.ok) {
    const msg =
      typeof parsed === 'object' && parsed && 'message' in parsed
        ? String((parsed as { message: unknown }).message)
        : res.statusText;
    throw new ApiError(msg || 'Request failed', res.status, parsed);
  }

  return parsed as T;
}

export function unwrapData<T>(body: unknown): T {
  if (
    body &&
    typeof body === 'object' &&
    'success' in body &&
    (body as { success: boolean }).success === true &&
    'data' in body
  ) {
    return (body as { data: T }).data;
  }
  return body as T;
}

/** Login — response is `{ access, refresh, user }` at top level */
export async function mobileLogin(body: { employee_id: string; password: string }) {
  return apiRequest<{ access: string; refresh: string; user: Record<string, unknown> }>(
    '/mobile/auth/login/',
    { method: 'POST', json: body, skipAuth: true },
  );
}

export type DashboardData = {
  today_visits: number;
  completed_visits: number;
  pending_visits: number;
  active_visit: VisitDto | null;
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

export async function fetchDashboard(token: string | null) {
  const raw = await apiRequest<unknown>('/mobile/dashboard/', { token });
  return unwrapData<DashboardData>(raw);
}

export async function fetchWorkStatus(token: string | null) {
  const raw = await apiRequest<unknown>('/mobile/work/status/', { token });
  return unwrapData<{ work_status: 'started' | 'not_started' }>(raw);
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
  const data = unwrapData<{ results?: VisitDto[] } | VisitDto[]>(raw);
  if (Array.isArray(data)) return data;
  return data.results ?? [];
}

export async function createVisit(
  token: string | null,
  body: Record<string, unknown>,
) {
  const raw = await apiRequest<unknown>('/mobile/visits/', {
    method: 'POST',
    token,
    json: body,
  });
  return unwrapData<{ visit_id?: number }>(raw);
}

export async function fetchVisitDetail(token: string | null, id: number) {
  const raw = await apiRequest<unknown>(`/visits/${id}/`, { token });
  if (raw && typeof raw === 'object' && 'success' in raw && !(raw as { success: boolean }).success) {
    throw new ApiError('Visit not found', 404, raw);
  }
  return raw as VisitDetailDto;
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

export async function fetchFarmersPage(token: string | null, page: number, search: string) {
  const q = new URLSearchParams({ page: String(page) });
  if (search.trim()) q.set('search', search.trim());
  const raw = await apiRequest<{ count: number; next: string | null; results: FarmerListItem[] }>(
    `/farmers/?${q.toString()}`,
    { token },
  );
  return raw;
}

export async function fetchFarmerDetail(token: string | null, id: number) {
  const raw = await apiRequest<unknown>(`/farmers/${id}/`, { token });
  return unwrapData<Record<string, unknown>>(raw);
}

export async function fetchFarmerVisitsPage(token: string | null, farmerId: number, page: number) {
  const raw = await apiRequest<{ count: number; next: string | null; results: VisitDto[] }>(
    `/farmers/${farmerId}/visits/?page=${page}`,
    { token },
  );
  return raw;
}

export async function fetchFarmerActivityPage(token: string | null, farmerId: number, page: number) {
  const raw = await apiRequest<{ count: number; next: string | null; results: Record<string, unknown>[] }>(
    `/farmers/${farmerId}/activity/?page=${page}`,
    { token },
  );
  return raw;
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
  const raw = await apiRequest<{ results?: MasterDistrict[] } | MasterDistrict[]>(
    '/masters/districts/?page_size=500',
    { token },
  );
  if (Array.isArray(raw)) return raw;
  return raw.results ?? [];
}

export async function fetchVillages(token: string | null, districtId: number) {
  const raw = await apiRequest<{ results?: MasterVillage[] } | MasterVillage[]>(
    `/masters/villages/?district=${districtId}&page_size=500`,
    { token },
  );
  if (Array.isArray(raw)) return raw;
  return raw.results ?? [];
}

export async function fetchCropsCatalog(token: string | null) {
  const raw = await apiRequest<MasterCrop[]>('/masters/crops/', { token });
  return Array.isArray(raw) ? raw : [];
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
