/**
 * Dynamic Expo config. Spreads static `app.json` values via the `config` argument.
 * Cleartext HTTP is enabled only for local/dev LAN testing — never for staging/production.
 */
module.exports = ({ config }) => {
  const appEnv = (
    process.env.EXPO_PUBLIC_APP_ENV ||
    process.env.APP_ENV ||
    config.extra?.appEnv ||
    'local'
  )
    .toString()
    .trim()
    .toLowerCase();

  const isProductionLike = ['prod', 'production', 'staging'].includes(appEnv);
  const apiBase = (process.env.EXPO_PUBLIC_API_BASE || '').trim().toLowerCase();
  const cleartextFlag = (process.env.EXPO_PUBLIC_ALLOW_CLEARTEXT || '').trim().toLowerCase();

  const allowCleartext =
    !isProductionLike &&
    (cleartextFlag === '1' ||
      cleartextFlag === 'true' ||
      cleartextFlag === 'yes' ||
      apiBase.startsWith('http://'));

  const existingPlugins = Array.isArray(config.plugins) ? [...config.plugins] : [];
  const withoutBuildProps = existingPlugins.filter((plugin) => {
    const name = Array.isArray(plugin) ? plugin[0] : plugin;
    return name !== 'expo-build-properties';
  });

  return {
    ...config,
    android: {
      ...(config.android || {}),
      permissions: [
        'ACCESS_COARSE_LOCATION',
        'ACCESS_FINE_LOCATION',
        // BACKGROUND_LOCATION intentionally omitted for Phase A (foreground fixes only).
      ],
    },
    plugins: [
      ...withoutBuildProps,
      [
        'expo-build-properties',
        {
          android: {
            usesCleartextTraffic: allowCleartext,
          },
        },
      ],
    ],
    extra: {
      ...(config.extra || {}),
      apiBaseUrl: process.env.EXPO_PUBLIC_API_BASE || undefined,
      appEnv,
      allowCleartext,
    },
  };
};
