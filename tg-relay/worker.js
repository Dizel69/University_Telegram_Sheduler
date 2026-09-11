/**
 * Релей Bot API на Cloudflare Workers.
 *
 * Нужен, когда с сервера не открывается api.telegram.org: bot-service ходит
 * на этот воркер (TELEGRAM_API_BASE), а воркер пересылает запрос в Telegram.
 *
 * Деплой: см. README, раздел Troubleshooting.
 */

const TELEGRAM_ORIGIN = "https://api.telegram.org";

// /bot<token>/<method>
const METHOD_PATH = /^\/bot(\d+:[A-Za-z0-9_-]+)\/([A-Za-z]+)$/;
// /file/bot<token>/<file_path> — скачивание файлов, путь может содержать слеши.
const FILE_PATH = /^\/file\/bot(\d+:[A-Za-z0-9_-]+)\/(.+)$/;

function jsonError(description, status) {
  return new Response(JSON.stringify({ ok: false, description }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST" && request.method !== "GET") {
      return jsonError("relay: method not allowed", 405);
    }

    const url = new URL(request.url);
    const match = METHOD_PATH.exec(url.pathname) || FILE_PATH.exec(url.pathname);
    if (!match) {
      return jsonError("relay: unsupported path", 404);
    }

    // Без этой проверки воркер станет открытым релеем для чужих ботов.
    if (env.ALLOWED_BOT_TOKEN && match[1] !== env.ALLOWED_BOT_TOKEN) {
      return jsonError("relay: token not allowed", 403);
    }

    const headers = new Headers();
    const contentType = request.headers.get("content-type");
    if (contentType) {
      headers.set("content-type", contentType);
    }

    let upstream;
    try {
      upstream = await fetch(TELEGRAM_ORIGIN + url.pathname + url.search, {
        method: request.method,
        headers,
        body: request.method === "GET" ? undefined : request.body,
      });
    } catch (err) {
      return jsonError(`relay: upstream failed: ${err}`, 502);
    }

    const outHeaders = new Headers();
    const upstreamType = upstream.headers.get("content-type");
    if (upstreamType) {
      outHeaders.set("content-type", upstreamType);
    }
    return new Response(upstream.body, { status: upstream.status, headers: outHeaders });
  },
};
