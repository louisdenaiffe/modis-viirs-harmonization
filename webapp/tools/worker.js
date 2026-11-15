// Cloudflare Worker in front of the data files. Cloudflare's static file hosting always sends
// whole files, but the app asks for small pieces of big data files ("Range" requests). This
// answers those requests with just the bytes asked for (HTTP 206), streaming the file and
// skipping what is not needed. Every other request is served by Cloudflare as usual.
//
// It also answers data/factors/<tile>.bin from the bundles made by tools/deploy.sh
// (data/factorpacks/<10-degree block>.bin), which keep the site under Cloudflare's file limit.
const packs = new Map();                            // the last few bundles read, newest last
function readPack(env, url, block) {
  if (packs.has(block)) { const p = packs.get(block); packs.delete(block); packs.set(block, p); return p; }
  const p = env.ASSETS.fetch(new URL(`/data/factorpacks/${block}.bin`, url)).then(async res => {
    if (res.status !== 200) return null;
    const buf = await res.arrayBuffer(), n = new DataView(buf).getUint32(0, true);
    return { buf, start: 4 + n, table: JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, n))) };
  });
  p.catch(() => packs.delete(block));
  packs.set(block, p);
  if (packs.size > 8) packs.delete(packs.keys().next().value);   // at most about 30 MB in memory
  return p;
}
async function factorFile(env, url, la, lo) {
  const pack = await readPack(env, url, `${Math.floor(la / 10) * 10}_${Math.floor(lo / 10) * 10}`);
  const entry = pack && pack.table[`${la}_${lo}`];
  if (!entry) return new Response('Not found', { status: 404 });
  const body = pack.buf.slice(pack.start + entry[0], pack.start + entry[0] + entry[1]);
  return new Response(body, { headers: { 'Content-Type': 'application/octet-stream', 'Cache-Control': 'public, max-age=3600' } });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const fac = /^\/data\/factors\/(-?\d+)_(-?\d+)\.bin$/.exec(url.pathname);
    if (fac) return factorFile(env, url, Number(fac[1]), Number(fac[2]));
    const range = request.headers.get('Range');
    const res = await env.ASSETS.fetch(new Request(request.url, { method: 'GET', headers: { 'Accept-Encoding': 'identity' } }));
    const m = range && /^bytes=(\d+)-(\d*)$/.exec(range);
    if (!m || res.status !== 200 || !res.body) return res;

    let size = Number(res.headers.get('Content-Length'));
    let body = res.body;
    if (!size) {                                    // length unknown: read the file to find it
      const buf = await res.arrayBuffer();
      size = buf.byteLength;
      body = new Blob([buf]).stream();
    }
    const start = Number(m[1]), end = m[2] ? Math.min(Number(m[2]), size - 1) : size - 1;
    if (start > end) return new Response(null, { status: 416, headers: { 'Content-Range': `bytes */${size}` } });

    let pos = 0;
    const cut = new TransformStream({
      transform(chunk, out) {
        const a = Math.max(0, start - pos), b = Math.min(chunk.length, end + 1 - pos);
        if (b > a) out.enqueue(chunk.subarray(a, b));
        pos += chunk.length;
        if (pos > end) out.terminate();
      }
    });
    body.pipeTo(cut.writable).catch(() => {});
    const headers = new Headers(res.headers);
    headers.set('Content-Range', `bytes ${start}-${end}/${size}`);
    headers.set('Content-Length', String(end - start + 1));
    headers.set('Accept-Ranges', 'bytes');
    return new Response(cut.readable, { status: 206, headers });
  }
};
