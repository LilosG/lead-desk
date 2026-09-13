// @ts-check
import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';

import node from '@astrojs/node';

export default defineConfig({
  vite: {
    plugins: [tailwindcss()],
    server: {
      proxy: {
        '/api': {
          target: 'http:' + '//' + '127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
  },

  adapter: node({
    mode: 'standalone',
  }),
});