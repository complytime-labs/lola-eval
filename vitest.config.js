import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['tests/node/**/*.test.js'],
    environment: 'node',
    testTimeout: 30000,
    pool: 'forks',
  },
});
