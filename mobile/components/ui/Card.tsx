import React from 'react';
import { StyleSheet, View, ViewProps } from 'react-native';
import { palette, radius, shadow, space } from '@/constants/theme';

export function Card({ children, style, ...rest }: ViewProps) {
  return (
    <View style={[styles.card, shadow.card, style]} {...rest}>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: palette.surface,
    borderRadius: radius.lg,
    padding: space.md,
    borderWidth: 1,
    borderColor: palette.border,
  },
});
