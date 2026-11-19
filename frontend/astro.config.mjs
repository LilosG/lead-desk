// @ts-check
import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';
import cloudflare from '@astrojs/cloudflare';

export default defineConfig({
  output: 'server',

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

  adapter: cloudflare(),
});