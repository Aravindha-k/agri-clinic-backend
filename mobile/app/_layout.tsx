import { AuthProvider, useAuth } from '@/context/AuthContext';
import { palette } from '@/constants/theme';
import FontAwesome from '@expo/vector-icons/FontAwesome';
import { ThemeProvider, DefaultTheme } from '@react-navigation/native';
import { useFonts } from 'expo-font';
import { Stack, useRouter, useSegments } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect } from 'react';
import { ActivityIndicator, View } from 'react-native';
import 'react-native-reanimated';

export { ErrorBoundary } from 'expo-router';

SplashScreen.preventAutoHideAsync();

const AppTheme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    primary: palette.primary,
    background: palette.background,
    card: palette.surface,
    text: palette.text,
    border: palette.border,
    notification: palette.accent,
  },
};

function AuthNavigator({ children }: { children: React.ReactNode }) {
  const { ready, token } = useAuth();
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    if (!ready) return;
    const root = segments[0];
    const onLogin = root === 'login';
    const onIndex = root === 'index' || root === undefined;

    if (!token && !onLogin && !onIndex) {
      router.replace('/login');
      return;
    }
    if (token && onLogin) {
      router.replace('/(tabs)');
    }
  }, [ready, token, segments, router]);

  if (!ready) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: palette.background }}>
        <ActivityIndicator color={palette.primary} size="large" />
      </View>
    );
  }

  return <>{children}</>;
}

export default function RootLayout() {
  const [loaded, error] = useFonts({
    SpaceMono: require('../assets/fonts/SpaceMono-Regular.ttf'),
    ...FontAwesome.font,
  });

  useEffect(() => {
    if (error) throw error;
  }, [error]);

  useEffect(() => {
    if (loaded) SplashScreen.hideAsync();
  }, [loaded]);

  if (!loaded) return null;

  return (
    <AuthProvider>
      <ThemeProvider value={AppTheme}>
        <AuthNavigator>
          <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: palette.background } }}>
            <Stack.Screen name="index" />
            <Stack.Screen name="login" />
            <Stack.Screen name="(tabs)" />
            <Stack.Screen name="visit/[id]" />
            <Stack.Screen name="visit/create" />
            <Stack.Screen name="farmer/[id]" />
          </Stack>
        </AuthNavigator>
      </ThemeProvider>
    </AuthProvider>
  );
}
