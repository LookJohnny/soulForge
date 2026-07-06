import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    hmr: false,
    watch: {
      ignored: ['**/outputs/**', '**/.git/**', '**/node_modules/**'],
    },
  },
});
