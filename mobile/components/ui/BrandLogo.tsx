import { useEffect } from 'react';
import { Image, StyleSheet, Text, View } from 'react-native';
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withTiming,
} from 'react-native-reanimated';
import { palette, typography } from '@/constants/theme';

type Props = {
  size?: number;
  showTitle?: boolean;
  animate?: boolean;
};

export function BrandLogo({ size = 72, showTitle = false, animate = true }: Props) {
  const opacity = useSharedValue(animate ? 0 : 1);
  const scale = useSharedValue(animate ? 0.88 : 1);
  const breathe = useSharedValue(1);

  useEffect(() => {
    if (!animate) return;
    opacity.value = withDelay(120, withTiming(1, { duration: 700, easing: Easing.out(Easing.cubic) }));
    scale.value = withTiming(1, { duration: 700, easing: Easing.out(Easing.cubic) });
    breathe.value = withDelay(
      900,
      withRepeat(
        withSequence(
          withTiming(1.03, { duration: 1800, easing: Easing.inOut(Easing.ease) }),
          withTiming(1, { duration: 1800, easing: Easing.inOut(Easing.ease) }),
        ),
        -1,
        false,
      ),
    );
  }, [animate, opacity, scale, breathe]);

  const logoStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
    transform: [{ scale: scale.value * breathe.value }],
  }));

  const titleStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
  }));

  return (
    <View style={styles.wrap}>
      <Animated.View style={logoStyle}>
        <View style={[styles.ring, { width: size + 16, height: size + 16, borderRadius: (size + 16) * 0.24 }]}>
          <Image
            source={require('@/assets/images/icon.png')}
            style={{ width: size, height: size, borderRadius: size * 0.22 }}
            resizeMode="contain"
            accessibilityLabel="Agri Clinic"
          />
        </View>
      </Animated.View>
      {showTitle ? (
        <Animated.View style={titleStyle}>
          <Text style={styles.title}>Agri Clinic</Text>
          <Text style={styles.tagline}>Field team</Text>
        </Animated.View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center', gap: 10 },
  ring: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: palette.accentSoft,
    borderWidth: 1,
    borderColor: palette.border,
  },
  title: {
    ...typography.subtitle,
    color: palette.primary,
    textAlign: 'center',
    letterSpacing: 0.2,
  },
  tagline: {
    ...typography.caption,
    textAlign: 'center',
    color: palette.textMuted,
    marginTop: 2,
  },
});
