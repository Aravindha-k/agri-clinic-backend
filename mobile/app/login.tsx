import { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { router } from 'expo-router';
import { useAuth } from '@/context/AuthContext';
import { palette, radius, space, typography } from '@/constants/theme';
import { Button } from '@/components/ui/Button';
import { ApiError } from '@/lib/api';

export default function LoginScreen() {
  const { signIn, token } = useAuth();
  const [employeeId, setEmployeeId] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (token) {
    router.replace('/(tabs)');
    return null;
  }

  async function onSubmit() {
    setError(null);
    if (!employeeId.trim() || !password) {
      setError('Enter employee ID and password.');
      return;
    }
    setLoading(true);
    try {
      await signIn(employeeId, password);
      router.replace('/(tabs)');
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : 'Sign-in failed.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.wrap}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={styles.card}>
        <Text style={typography.overline}>Agri Clinic</Text>
        <Text style={styles.title}>Employee sign in</Text>
        <Text style={[typography.caption, styles.hint]}>Use your field employee ID (e.g. EMP-101).</Text>
        <Text style={styles.label}>Employee ID</Text>
        <TextInput
          value={employeeId}
          onChangeText={setEmployeeId}
          autoCapitalize="characters"
          placeholder="EMP-101"
          placeholderTextColor={palette.textMuted}
          style={styles.input}
        />
        <Text style={styles.label}>Password</Text>
        <TextInput
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          placeholder="••••••••"
          placeholderTextColor={palette.textMuted}
          style={styles.input}
        />
        {error ? <Text style={styles.err}>{error}</Text> : null}
        <View style={{ marginTop: space.lg }}>
          <Button title="Continue" onPress={onSubmit} loading={loading} />
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    backgroundColor: palette.background,
    justifyContent: 'center',
    padding: space.lg,
  },
  card: {
    backgroundColor: palette.surface,
    borderRadius: radius.lg,
    padding: space.lg,
    borderWidth: 1,
    borderColor: palette.border,
  },
  title: { ...typography.title, marginTop: space.xs, marginBottom: space.sm },
  hint: { marginBottom: space.md },
  label: { ...typography.caption, marginBottom: space.xs, color: palette.textSecondary },
  input: {
    borderWidth: 1,
    borderColor: palette.border,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    paddingVertical: space.sm,
    fontSize: 16,
    color: palette.text,
    marginBottom: space.sm,
    backgroundColor: palette.background,
  },
  err: { ...typography.caption, marginTop: space.xs, color: palette.danger },
});
