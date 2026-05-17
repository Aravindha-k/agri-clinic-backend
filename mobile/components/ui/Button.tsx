import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  ViewStyle,
} from 'react-native';
import { palette, radius, space, typography } from '@/constants/theme';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';

export function Button({
  title,
  onPress,
  variant = 'primary',
  disabled,
  loading,
  style,
}: {
  title: string;
  onPress: () => void;
  variant?: Variant;
  disabled?: boolean;
  loading?: boolean;
  style?: ViewStyle;
}) {
  const bg =
    variant === 'primary'
      ? palette.primary
      : variant === 'secondary'
        ? palette.accentSoft
        : variant === 'danger'
          ? palette.danger
          : 'transparent';
  const border =
    variant === 'secondary'
      ? { borderWidth: 1, borderColor: palette.primaryMuted }
      : {};
  const color =
    variant === 'primary' || variant === 'danger'
      ? '#fff'
      : variant === 'secondary'
        ? palette.primary
        : palette.primary;

  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [
        styles.base,
        { backgroundColor: bg },
        border,
        (disabled || loading) && styles.dim,
        pressed && variant === 'ghost' && { opacity: 0.7 },
        style,
      ]}>
      {loading ? (
        <ActivityIndicator color={variant === 'secondary' ? palette.primary : '#fff'} />
      ) : (
        <Text style={[typography.caption, { color, fontSize: 15 }]}>{title}</Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    paddingVertical: space.sm,
    paddingHorizontal: space.lg,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 48,
  },
  dim: { opacity: 0.55 },
});
