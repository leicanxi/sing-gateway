import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const gateway = process.env.SING_GATEWAY_URL ?? 'http://127.0.0.1:9001';
const apiProxy = {
  '/v1': {
    target: gateway,
    changeOrigin: true,
  },
};

const page = (name: string) => fileURLToPath(new URL(name, import.meta.url));

// The plaza is deployed as plain files in a static webroot, so every asset URL
// stays relative (`base: './'`). Both `vite dev` and `vite preview` proxy the
// gateway so the catalog loads without a second origin.
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: apiProxy,
  },
  preview: {
    proxy: apiProxy,
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    target: 'es2022',
    rollupOptions: {
      input: {
        index: page('index.html'),
        account: page('account.html'),
      },
    },
  },
});
