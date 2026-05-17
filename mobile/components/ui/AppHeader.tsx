import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { palette, shadow, space, typography } from '@/constants/theme';

export function AppHeader({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
}) {
  const inset = useSafeAreaInsets();
  return (
    <View style={[styles.wrap, shadow.header, { paddingTop: inset.top + space.sm }]}>
      <View style={styles.row}>
        <View style={styles.textCol}>
          <Text style={typography.overline}>Agri Clinic</Text>
          <Text style={styles.title}>{title}</Text>
          {subtitle ? <Text style={typography.caption}>{subtitle}</Text> : null}
        </View>
        {right}
      </View>
    </View>
  );
}

export function BackHeader({
  title,
  onBack,
}: {
  title: string;
  onBack: () => void;
}) {
  const inset = useSafeAreaInsets();
  return (
    <View style={[styles.wrap, shadow.header, { paddingTop: inset.top + space.sm }]}>
      <View style={styles.row}>
        <Pressable onPress={onBack} hitSlop={12} accessibilityRole="button">
          <Ionicons name="chevron-back" size={26} color={palette.primary} />
        </Pressable>
        <Text style={[typography.subtitle, { flex: 1, marginLeft: space.xs }]}>{title}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: palette.surface,
    paddingHorizontal: space.md,
    paddingBottom: space.md,
    borderBottomWidth: 1,
    borderBottomColor: palette.border,
  },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  textCol: { flex: 1, paddingRight: space.sm },
  title: { ...typography.title, marginTop: 4 },
});
