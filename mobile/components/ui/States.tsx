import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { palette, space, typography } from '@/constants/theme';
import { Button } from '@/components/ui/Button';

export function LoadingBlock({ label = 'Loading…' }: { label?: string }) {
  return (
    <View style={styles.center}>
      <ActivityIndicator size="large" color={palette.primary} />
      <Text style={[typography.caption, { marginTop: space.sm }]}>{label}</Text>
    </View>
  );
}

export function EmptyState({
  title,
  detail,
  actionLabel,
  onAction,
}: {
  title: string;
  detail?: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <View style={styles.center}>
      <Ionicons name="leaf-outline" size={40} color={palette.textMuted} />
      <Text style={[typography.subtitle, { marginTop: space.md, textAlign: 'center' }]}>{title}</Text>
      {detail ? (
        <Text style={[typography.caption, { marginTop: space.xs, textAlign: 'center' }]}>
          {detail}
        </Text>
      ) : null}
      {actionLabel && onAction ? (
        <View style={{ marginTop: space.lg, alignSelf: 'stretch' }}>
          <Button title={actionLabel} onPress={onAction} variant="primary" />
        </View>
      ) : null}
    </View>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <View style={styles.center}>
      <Ionicons name="warning-outline" size={40} color={palette.warning} />
      <Text style={[typography.body, { marginTop: space.md, textAlign: 'center' }]}>{message}</Text>
      {onRetry ? (
        <Pressable onPress={onRetry} style={{ marginTop: space.lg }}>
          <Text style={[typography.subtitle, { color: palette.primary }]}>Retry</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    padding: space.xl,
    alignItems: 'center',
    justifyContent: 'center',
  },
});

export function SectionTitle({ children }: { children: string }) {
  return <Text style={[typography.overline, { marginBottom: space.xs }]}>{children}</Text>;
}
