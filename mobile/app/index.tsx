import { Redirect } from 'expo-router';
import { useAuth } from '@/context/AuthContext';
import { View, ActivityIndicator } from 'react-native';
import { palette } from '@/constants/theme';

export default function Index() {
  const { ready, token } = useAuth();
  if (!ready) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: palette.background }}>
        <ActivityIndicator color={palette.primary} size="large" />
      </View>
    );
  }
  if (token) return <Redirect href="/(tabs)" />;
  return <Redirect href="/login" />;
}
