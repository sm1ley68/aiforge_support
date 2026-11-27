import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const { SOFTLINE_API_ORIGIN } = loadEnv(mode, '.', 'SOFTLINE_');
  const target = SOFTLINE_API_ORIGIN || 'http://127.0.0.1:8000';
  const proxy = { '/api': { target }, '/chats': { target } };
  return { server: { proxy }, preview: { proxy } };
});
