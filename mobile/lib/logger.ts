import Constants from 'expo-constants';

type LogLevel = 'info' | 'warn' | 'error';

type LogFields = Record<string, string | number | boolean | null | undefined>;

const APP_VERSION =
  Constants.expoConfig?.version ||
  (Constants.nativeAppVersion as string | undefined) ||
  'unknown';

function emit(level: LogLevel, operation: string, fields: LogFields = {}) {
  const payload = {
    ts: new Date().toISOString(),
    level,
    operation,
    appVersion: APP_VERSION,
    ...fields,
  };
  const line = `[AgriClinic] ${JSON.stringify(payload)}`;
  if (level === 'error') {
    console.error(line);
  } else if (level === 'warn') {
    console.warn(line);
  } else if (typeof __DEV__ !== 'undefined' && __DEV__) {
    console.log(line);
  }
}

/** Safe diagnostic logging — never pass tokens, passwords, or PII. */
export const appLog = {
  info(operation: string, fields?: LogFields) {
    emit('info', operation, fields);
  },
  warn(operation: string, fields?: LogFields) {
    emit('warn', operation, fields);
  },
  error(operation: string, fields?: LogFields) {
    emit('error', operation, fields);
  },
};
