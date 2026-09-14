import { defineMiddleware } from 'astro:middleware';

const PUBLIC_PATHS = new Set(['/login']);
const API_ORIGIN = import.meta.env.DEV
  ? 'http://127.0.0.1:8000'
  : 'https://138-199-222-64.nip.io';

function isPublicAsset(pathname: string): boolean {
  return (
    pathname.startsWith('/_astro/') ||
    pathname === '/favicon.ico' ||
    pathname === '/favicon.svg' ||
    pathname === '/robots.txt'
  );
}

export const onRequest = defineMiddleware(async (context, next) => {
  const pathname = context.url.pathname;

  if (isPublicAsset(pathname)) {
    return next();
  }

  const cookie = context.request.headers.get('cookie') ?? '';
  let authenticated = false;

  if (cookie) {
    try {
      const response = await fetch(`${API_ORIGIN}/api/auth/session`, {
        headers: {
          Accept: 'application/json',
          Cookie: cookie,
        },
        redirect: 'manual',
      });
      authenticated = response.ok;
    } catch {
      authenticated = false;
    }
  }

  if (PUBLIC_PATHS.has(pathname)) {
    if (authenticated) {
      return context.redirect('/');
    }
    return next();
  }

  if (!authenticated) {
    const destination = encodeURIComponent(
      `${context.url.pathname}${context.url.search}`,
    );
    return context.redirect(`/login?next=${destination}`);
  }

  return next();
});
