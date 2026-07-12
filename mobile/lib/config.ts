import Constants from 'expo-constants';
import { Platform } from 'react-native';

type ExpoExtra = {
  apiBaseUrl?: string;
  appEnv?: string;
  allowCleartext?: boolean;
};

const extra = (Constants.expoConfig?.extra ?? {}) as ExpoExtra;

function stripTrailingSlash(url: string): string {
  return url.replace(/\/$/, '');
}

/**
 * API root including `/api/v1` (no trailing slash).
 * Priority: EXPO_PUBLIC_API_BASE → app.config extra.apiBaseUrl → platform-aware local default.
 */
const fromEnv = process.env.EXPO_PUBLIC_API_BASE?.trim();
const fromExtra = extra.apiBaseUrl?.trim();

/** Emulator loopback to host machine; physical devices must set EXPO_PUBLIC_API_BASE to a LAN IP. */
const LOCAL_DEFAULT =
  Platform.OS === 'android'
    ? 'http://10.0.2.2:8000/api/v1'
    : 'http://127.0.0.1:8000/api/v1';

export const API_BASE_URL = stripTrailingSlash(fromEnv || fromExtra || LOCAL_DEFAULT);

export const APP_ENV = (
  process.env.EXPO_PUBLIC_APP_ENV ||
  extra.appEnv ||
  process.env.APP_ENV ||
  'local'
)
  .trim()
  .toLowerCase();

export const IS_PRODUCTION_LIKE = ['prod', 'production', 'staging'].includes(APP_ENV);

export const APP_VERSION =
  Constants.expoConfig?.version ||
  (Constants.nativeAppVersion as string | undefined) ||
  '1.0.0';

export const LOCATION_SYNC_INTERVAL_MS = 30 * 60 * 1000;
export const WORKDAY_AUTO_STOP_HOURS = 9;

export type ApiConfigIssue = {
  code: 'MISSING_LAN_HINT' | 'HTTP_IN_PRODUCTION' | 'LOCALHOST_ON_DEVICE';
  message: string;
};

/** Origin used for `/healthz/` (strip `/api/v1`). */
export function apiOriginFromBase(apiBase: string = API_BASE_URL): string {
  return apiBase.replace(/\/api\/v1\/?$/i, '') || apiBase;
}

export function displayApiHost(apiBase: string = API_BASE_URL): string {
  try {
    const u = new URL(apiBase);
    return `${u.protocol}//${u.host}`;
  } catch {
    return apiBase;
  }
}

export function isLoopbackHost(apiBase: string = API_BASE_URL): boolean {
  try {
    const host = new URL(apiBase).hostname;
    return host === '127.0.0.1' || host === 'localhost' || host === '::1';
  } catch {
    return false;
  }
}

export function isHttpUrl(apiBase: string = API_BASE_URL): boolean {
  return apiBase.toLowerCase().startsWith('http://');
}

/**
 * Non-blocking configuration warnings for diagnostics / QA.
 * Does not throw — physical-device LAN testing must set EXPO_PUBLIC_API_BASE explicitly.
 */
export function getApiConfigIssues(): ApiConfigIssue[] {
  const issues: ApiConfigIssue[] = [];
  const configuredExplicitly = Boolean(fromEnv || fromExtra);

  if (IS_PRODUCTION_LIKE && isHttpUrl()) {
    issues.push({
      code: 'HTTP_IN_PRODUCTION',
      message:
        'This build targets a production-like environment but API base uses HTTP. Use HTTPS for staging/production.',
    });
  }

  if (!configuredExplicitly && Platform.OS === 'android') {
    issues.push({
      code: 'MISSING_LAN_HINT',
      message:
        'EXPO_PUBLIC_API_BASE is not set. Emulator default is 10.0.2.2; a physical phone needs your PC LAN IP (see mobile/.env.example).',
    });
  }

  if (configuredExplicitly && isLoopbackHost() && Platform.OS === 'android') {
    issues.push({
      code: 'LOCALHOST_ON_DEVICE',
      message:
        'API base points at localhost/127.0.0.1. On a physical Android phone that is the phone itself — use the PC LAN IP or 10.0.2.2 for the emulator.',
    });
  }

  return issues;
}

export function healthCheckUrl(apiBase: string = API_BASE_URL): string {
  return `${apiOriginFromBase(apiBase)}/healthz/`;
}
