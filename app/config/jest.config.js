export default {
  testEnvironment: 'node',
  testTimeout: 30000,
  preset: 'jest-react',
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx', 'json'],
  setupFilesAfterEnv: ['<rootDir>/tests/setup.ts'],
  moduleNameMapping: {
    '^@/(.*)$': '<rootDir>/app/$1',
  },
};
