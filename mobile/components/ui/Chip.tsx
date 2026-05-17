import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text } from 'react-native';
import { palette, radius, space, typography } from '@/constants/theme';

export function Chip({
  label,
  selected,
  onPress,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={[
        styles.chip,
        selected && styles.chipOn,
      ]}>
      <Text style={[typography.caption, selected ? styles.labelOn : styles.label]}>{label}</Text>
    </Pressable>
  );
}

export function ChipRow({
  options,
  value,
  onChange,
}: {
  options: { key: string; label: string }[];
  value: string;
  onChange: (key: string) => void;
}) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.row}>
      {options.map((o) => (
        <Chip
          key={o.key}
          label={o.label}
          selected={value === o.key}
          onPress={() => onChange(o.key)}
        />
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { flexGrow: 0 },
  chip: {
    paddingHorizontal: space.md,
    paddingVertical: space.xs,
    borderRadius: radius.pill,
    backgroundColor: palette.background,
    borderWidth: 1,
    borderColor: palette.border,
    marginRight: space.xs,
  },
  chipOn: {
    backgroundColor: palette.accentSoft,
    borderColor: palette.primaryMuted,
  },
  label: { color: palette.textSecondary },
  labelOn: { color: palette.primary, fontWeight: '600' },
});
