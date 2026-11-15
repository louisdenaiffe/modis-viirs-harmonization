// Cloudflare Worker in front of the data files. Cloudflare's static file hosting always sends
// whole files, but the app asks for small pieces of big data files ("Range" requests). This
// answers those requests with just the bytes asked for (HTTP 206), streaming the file and
// skipping what is not needed. Every other request is served by Cloudflare as usual.
export default {
  async fetch(request, env) {
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
