// Vitest configuration used by the sandbox runner.
// Loaded with `--configLoader runner` so nothing is written next to the
// (read-only) runner install. The project's own vite/vitest config is NOT
// loaded: it may reference plugins that are not installed (network is off).
const NM = '/opt/runner/node_modules';

export default {
  resolve: {
    alias: [
      // Let project tests that `import { it } from 'vitest'` resolve to the bundled copy.
      { find: /^vitest$/, replacement: `${NM}/vitest/dist/index.js` },
      { find: /^@vitest\/coverage-v8$/, replacement: `${NM}/@vitest/coverage-v8/dist/index.js` },
    ],
  },
  server: { fs: { allow: ['/work', NM] } },
  test: {
    globals: true,
    include: ['**/*.{test,spec}.{js,mjs,cjs,ts,mts,cts,jsx,tsx}'],
    exclude: ['**/node_modules/**', '**/dist/**'],
    testTimeout: 10000,
    pool: 'forks',
    poolOptions: { forks: { singleFork: true } },
    coverage: {
      provider: 'custom',
      customProviderModule: `${NM}/@vitest/coverage-v8/dist/index.js`,
      exclude: ['testpilot_generated/**', '**/*.{test,spec}.*', '**/node_modules/**'],
    },
  },
};
