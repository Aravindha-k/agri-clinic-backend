import { API_BASE_URL, APP_ENV, APP_VERSION, getApiConfigIssues, healthCheckUrl, displayApiHost } from '@/lib/config';
import { getAccessToken, getDeviceSessionId, getRefreshToken } from '@/lib/authStorage';
import { appLog } from '@/lib/logger';

export type ConnectivityDiagnostic = {
  apiHost: string;
  apiBasePath: string;
  environment: string;
  appVersion: string;
  reachable: boolean | null;
  httpStatus: number | null;
  healthMessage: string;
  authRestored: boolean;
  hasAccessToken: boolean;
  hasRefreshToken: boolean;
  hasDeviceSession: boolean;
  deviceSessionMasked: string | null;
  configWarnings: string[];
  checkedAt: string;
};

function maskId(value: string | null): string | null {
  if (!value) return null;
  if (value.length <= 8) return '••••';
  return `${value.slice(0, 4)}…${value.slice(-4)}`;
}

/** Probe backend `/healthz/` (public) and report local auth presence without exposing secrets. */
export async function runConnectivityDiagnostic(): Promise<ConnectivityDiagnostic> {
  const warnings = getApiConfigIssues().map((i) => i.message);
  const access = await getAccessToken();
  const refresh = await getRefreshToken();
  const session = await getDeviceSessionId();
  const url = healthCheckUrl();

  let reachable: boolean | null = null;
  let httpStatus: number | null = null;
  let healthMessage = 'Not checked';

  try {
    appLog.info('diagnostics.health_start', { host: displayApiHost() });
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    const res = await fetch(url, { method: 'GET', signal: controller.signal });
    clearTimeout(timer);
    httpStatus = res.status;
    reachable = res.ok;
    let bodyText = '';
    try {
      bodyText = await res.text();
      const json = JSON.parse(bodyText) as { status?: string; database?: string };
      healthMessage =
        json.status && json.database
          ? `status=${json.status}, database=${json.database}`
          : bodyText.slice(0, 120) || res.statusText;
    } catch {
      healthMessage = bodyText.slice(0, 120) || res.statusText || 'OK';
    }
    appLog.info('diagnostics.health_done', { status: res.status, reachable });
  } catch (e) {
    reachable = false;
    httpStatus = null;
    healthMessage =
      e instanceof Error && e.name === 'AbortError'
        ? 'Timed out contacting /healthz/'
        : 'Could not reach API host (network, firewall, wrong IP, or server down)';
    appLog.warn('diagnostics.health_failed');
  }

  return {
    apiHost: displayApiHost(),
    apiBasePath: API_BASE_URL.endsWith('/api/v1') ? '/api/v1' : API_BASE_URL,
    environment: APP_ENV,
    appVersion: APP_VERSION,
    reachable,
    httpStatus,
    healthMessage,
    authRestored: Boolean(access && session),
    hasAccessToken: Boolean(access),
    hasRefreshToken: Boolean(refresh),
    hasDeviceSession: Boolean(session),
    deviceSessionMasked: maskId(session),
    configWarnings: warnings,
    checkedAt: new Date().toISOString(),
  };
}
