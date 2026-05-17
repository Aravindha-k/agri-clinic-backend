import * as Location from 'expo-location';

let granted = false;

export async function captureSilentLocation(): Promise<GeoPoint | null> {
  try {
    let { status } = await Location.getForegroundPermissionsAsync();
    if (status !== 'granted') {
      ({ status } = await Location.requestForegroundPermissionsAsync());
    }
    if (status !== 'granted') return null;
    granted = true;
    const pos = await Location.getCurrentPositionAsync({
      accuracy: Location.Accuracy.Balanced,
    });
    return {
      latitude: pos.coords.latitude,
      longitude: pos.coords.longitude,
      accuracy: pos.coords.accuracy ?? null,
    };
  } catch {
    return null;
  }
}

export async function hasLocationPermission(): Promise<boolean> {
  if (granted) return true;
  const { status } = await Location.getForegroundPermissionsAsync();
  return status === 'granted';
}

export type GeoPoint = { latitude: number; longitude: number; accuracy: number | null };
