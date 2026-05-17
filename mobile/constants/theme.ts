import { Platform, TextStyle, ViewStyle } from 'react-native';

/** Agri Clinic — field employee accent: deep green + soft mint, light gray shells */
export const palette = {
  primary: '#14532d',
  primaryMuted: '#166534',
  accent: '#86efac',
  accentSoft: '#dcfce7',
  background: '#e8ece9',
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  border: '#d1d5db',
  text: '#0f172a',
  textSecondary: '#475569',
  textMuted: '#64748b',
  danger: '#b91c1c',
  warning: '#b45309',
  success: '#15803d',
} as const;

export const space = {
  xxs: 4,
  xs: 8,
  sm: 12,
  md: 16,
  lg: 20,
  xl: 24,
  xxl: 32,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  pill: 999,
} as const;

export const shadow = {
  card: Platform.select<ViewStyle>({
    ios: {
      shadowColor: '#0f172a',
      shadowOffset: { width: 0, height: 2 },
      shadowOpacity: 0.06,
      shadowRadius: 8,
    },
    android: { elevation: 2 },
    default: {},
  }),
  header: Platform.select<ViewStyle>({
    ios: {
      shadowColor: '#0f172a',
      shadowOffset: { width: 0, height: 1 },
      shadowOpacity: 0.05,
      shadowRadius: 4,
    },
    android: { elevation: 1 },
    default: {},
  }),
} as const;

export const typography = {
  title: {
    fontSize: 22,
    fontWeight: '700' as TextStyle['fontWeight'],
    color: palette.text,
    letterSpacing: -0.3,
  },
  subtitle: {
    fontSize: 17,
    fontWeight: '600' as TextStyle['fontWeight'],
    color: palette.text,
  },
  body: {
    fontSize: 15,
    fontWeight: '400' as TextStyle['fontWeight'],
    color: palette.text,
    lineHeight: 22,
  },
  caption: {
    fontSize: 13,
    fontWeight: '500' as TextStyle['fontWeight'],
    color: palette.textSecondary,
    lineHeight: 18,
  },
  overline: {
    fontSize: 11,
    fontWeight: '600' as TextStyle['fontWeight'],
    color: palette.primaryMuted,
    textTransform: 'uppercase' as TextStyle['textTransform'],
    letterSpacing: 0.6,
  },
} as const;

export const tabBarTheme = {
  active: palette.primary,
  inactive: palette.textMuted,
  background: palette.surface,
  borderTop: palette.border,
};
