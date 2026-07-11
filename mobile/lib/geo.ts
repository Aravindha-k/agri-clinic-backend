import * as Location from 'expo-location';
import { Linking } from 'react-native';
import { appLog } from '@/lib/logger';

export type GeoPoint = { latitude: number; longitude: number; accuracy: number | null };

export type LocationCaptureFailure = 'denied' | 'services_off' | 'timeout' | 'unavailable';

export type LocationCaptureResult =
  | { ok: true; point: GeoPoint }
  | { ok: false; reason: LocationCaptureFailure };

const POSITION_TIMEOUT_MS = 15000;

let cachedPermission: Location.PermissionStatus | null = null;
let permissionRequest: Promise<Location.PermissionStatus> | null = null;

async function ensureForegroundPermission(): Promise<Location.PermissionStatus> {
  if (cachedPermission === Location.PermissionStatus.GRANTED) {
    return Location.PermissionStatus.GRANTED;
  }

  const current = await Location.getForegroundPermissionsAsync();
  cachedPermission = current.status;
  if (current.status === Location.PermissionStatus.GRANTED) {
    return Location.PermissionStatus.GRANTED;
  }

  // Do not re-prompt after the user has denied — avoids repeated system dialogs.
  if (current.status === Location.PermissionStatus.DENIED) {
    return Location.PermissionStatus.DENIED;
  }

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
    if (status !== Location.PermissionStatus.GRANTED) {
      appLog.warn('geo.permission_denied');
      return { ok: false, reason: 'denied' };
    }

    const servicesOn = await Location.hasServicesEnabledAsync();
    if (!servicesOn) {
      appLog.warn('geo.services_off');
      return { ok: false, reason: 'services_off' };
    }

    const pos = await withTimeout(
      Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      }),
      POSITION_TIMEOUT_MS,
    );

    const accuracy = pos.coords.accuracy ?? null;
    appLog.info('geo.capture_ok', {
      accuracy: accuracy != null ? Math.round(accuracy) : null,
    });

    return {
      ok: true,
      point: {
        latitude: pos.coords.latitude,
        longitude: pos.coords.longitude,
        accuracy,
      },
    };
  } catch (err) {
    if (err instanceof Error && err.message === 'timeout') {
      appLog.warn('geo.capture_timeout');
      return { ok: false, reason: 'timeout' };
    }
    appLog.warn('geo.capture_unavailable');
    return { ok: false, reason: 'unavailable' };
  }
}

/** Returns a point or null without throwing when permission/GPS fails. */
export async function captureSilentLocation(): Promise<GeoPoint | null> {
  const result = await captureLocation();
  return result.ok ? result.point : null;
}

export async function hasLocationPermission(): Promise<boolean> {
  if (cachedPermission === Location.PermissionStatus.GRANTED) return true;
  const { status } = await Location.getForegroundPermissionsAsync();
  cachedPermission = status;
  return status === Location.PermissionStatus.GRANTED;
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
