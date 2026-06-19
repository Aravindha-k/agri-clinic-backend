import * as Location from 'expo-location';
import { Linking } from 'react-native';

export type GeoPoint = { latitude: number; longitude: number; accuracy: number | null };

export type LocationCaptureFailure = 'denied' | 'services_off' | 'timeout' | 'unavailable';

export type LocationCaptureResult =
  | { ok: true; point: GeoPoint }
  | { ok: false; reason: LocationCaptureFailure };

const POSITION_TIMEOUT_MS = 15000;

let cachedPermission: Location.PermissionStatus | null = null;
let permissionRequest: Promise<Location.PermissionStatus> | null = null;

async function ensureForegroundPermission(): Promise<Location.PermissionStatus> {
  if (cachedPermission === 'granted') return 'granted';

  const current = await Location.getForegroundPermissionsAsync();
  cachedPermission = current.status;
  if (current.status === 'granted') return 'granted';

  // Do not re-prompt after the user has denied — avoids repeated system dialogs.
  if (current.status === 'denied') return 'denied';

  if (!permissionRequest) {
    permissionRequest = Location.requestForegroundPermissionsAsync()
      .then((res) => {
        cachedPermission = res.status;
        return res.status;
      })
      .finally(() => {
        permissionRequest = null;
      });
  }
  return permissionRequest;
}

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), ms);
    promise
      .then((value) => {
        clearTimeout(timer);
        resolve(value);
      })
      .catch((err) => {
        clearTimeout(timer);
        reject(err);
      });
  });
}

export async function captureLocation(): Promise<LocationCaptureResult> {
  try {
    const status = await ensureForegroundPermission();
    if (status !== 'granted') {
      return { ok: false, reason: 'denied' };
    }

    const servicesOn = await Location.hasServicesEnabledAsync();
    if (!servicesOn) {
      return { ok: false, reason: 'services_off' };
    }

    const pos = await withTimeout(
      Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      }),
      POSITION_TIMEOUT_MS,
    );

    return {
      ok: true,
      point: {
        latitude: pos.coords.latitude,
        longitude: pos.coords.longitude,
        accuracy: pos.coords.accuracy ?? null,
      },
    };
  } catch (err) {
    if (err instanceof Error && err.message === 'timeout') {
      return { ok: false, reason: 'timeout' };
    }
    return { ok: false, reason: 'unavailable' };
  }
}

/** Backward-compatible helper — returns a point or null without prompting again when denied. */
export async function captureSilentLocation(): Promise<GeoPoint | null> {
  const result = await captureLocation();
  return result.ok ? result.point : null;
}

export async function hasLocationPermission(): Promise<boolean> {
  if (cachedPermission === 'granted') return true;
  const { status } = await Location.getForegroundPermissionsAsync();
  cachedPermission = status;
  return status === 'granted';
}

export function locationFailureTitle(reason: LocationCaptureFailure): string {
  switch (reason) {
    case 'denied':
      return 'Location access';
    case 'services_off':
      return 'Location services off';
    case 'timeout':
      return 'Location unavailable';
    default:
      return 'Could not get location';
  }
}

export function locationFailureMessage(reason: LocationCaptureFailure): string {
  switch (reason) {
    case 'denied':
      return 'Turn on location permission for Agri Clinic in your phone settings. We only use it for workday and visit fixes.';
    case 'services_off':
      return 'Enable GPS / location services on your device, then try again.';
    case 'timeout':
      return 'Could not get a GPS fix right now. Move outdoors or wait a moment and try again.';
    default:
      return 'Location could not be read. Check GPS and try again.';
  }
}

export async function openLocationSettings(): Promise<void> {
  try {
    await Linking.openSettings();
  } catch {
    /* device may not support settings deep link */
  }
}
