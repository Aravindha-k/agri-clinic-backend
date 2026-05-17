import Constants from 'expo-constants';

const fromExtra =
  (Constants.expoConfig?.extra as { apiBaseUrl?: string } | undefined)?.apiBaseUrl;

/** Set `EXPO_PUBLIC_API_BASE` in `.env` or `extra.apiBaseUrl` in app.json */
export const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_BASE?.replace(/\/$/, '') ||
  fromExtra?.replace(/\/$/, '') ||
  'http://127.0.0.1:8000/api/v1';

export const LOCATION_SYNC_INTERVAL_MS = 30 * 60 * 1000;
export const WORKDAY_AUTO_STOP_HOURS = 9;
