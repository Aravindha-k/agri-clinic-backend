import AsyncStorage from '@react-native-async-storage/async-storage';

const ACCESS = 'agri_access';
const REFRESH = 'agri_refresh';
const WORKDAY_START = 'agri_workday_started_at';
const LAST_SYNC = 'agri_last_location_sync_at';

export async function saveTokens(access: string, refresh: string) {
  await AsyncStorage.multiSet([
    [ACCESS, access],
    [REFRESH, refresh],
  ]);
}

export async function getAccessToken() {
  return AsyncStorage.getItem(ACCESS);
}

export async function getRefreshToken() {
  return AsyncStorage.getItem(REFRESH);
}

export async function clearTokens() {
  await AsyncStorage.multiRemove([ACCESS, REFRESH, WORKDAY_START, LAST_SYNC]);
}

export async function setWorkdayStartedAt(iso: string | null) {
  if (!iso) await AsyncStorage.removeItem(WORKDAY_START);
  else await AsyncStorage.setItem(WORKDAY_START, iso);
}

export async function getWorkdayStartedAt() {
  return AsyncStorage.getItem(WORKDAY_START);
}

export async function setLastLocationSyncAt(iso: string | null) {
  if (!iso) await AsyncStorage.removeItem(LAST_SYNC);
  else await AsyncStorage.setItem(LAST_SYNC, iso);
}

export async function getLastLocationSyncAt() {
  return AsyncStorage.getItem(LAST_SYNC);
}
