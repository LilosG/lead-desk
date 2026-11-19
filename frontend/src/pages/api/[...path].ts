import type { APIRoute } from 'astro';

export const prerender = false;

const API_ORIGIN = 'https://138-199-222-64.nip.io';

const proxy: APIRoute = async ({ request, url }) => {
  const target = `${API_ORIGIN}${url.pathname}${url.search}`;

  const headers = new Headers(request.headers);
  headers.delete('host');

  const hasBody = request.method !== 'GET' && request.method !== 'HEAD';
  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? request.body : undefined,
    redirect: 'manual',
    // @ts-expect-error required by the Workers runtime for streamed request bodies
    duplex: hasBody ? 'half' : undefined,
  });

  const out = new Headers();
  for (const [k, v] of upstream.headers) {
    if (k.toLowerCase() !== 'set-cookie') out.append(k, v);
  }
  for (const c of upstream.headers.getSetCookie()) out.append('set-cookie', c);
  out.set('Cache-Control', 'no-store');

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: out,
  });
};

export const ALL: APIRoute = proxy;
