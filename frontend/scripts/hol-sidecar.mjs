import { createServer } from 'node:http';
import { pathToFileURL } from 'node:url';
import { RegistryBrokerClient } from '@hashgraphonline/standards-sdk';

const DEFAULT_BASE_URL = 'https://hol.org/registry/api/v1';
const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 8040;

function jsonResponse(res, statusCode, payload) {
  res.writeHead(statusCode, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(payload));
}

async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }
  if (chunks.length === 0) {
    return {};
  }
  const text = Buffer.concat(chunks).toString('utf8').trim();
  if (!text) {
    return {};
  }
  return JSON.parse(text);
}

function firstString(values) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
  }
  return null;
}

export function buildSidecarConfig(env = process.env) {
  const baseUrl = (env.REGISTRY_BROKER_API_URL || DEFAULT_BASE_URL).trim();
  const host = (env.HOL_SDK_SIDECAR_HOST || DEFAULT_HOST).trim() || DEFAULT_HOST;
  const parsedPort = Number.parseInt(env.HOL_SDK_SIDECAR_PORT || `${DEFAULT_PORT}`, 10);
  return {
    baseUrl,
    host,
    port: Number.isFinite(parsedPort) && parsedPort > 0 ? parsedPort : DEFAULT_PORT,
    apiKey: (env.REGISTRY_BROKER_API_KEY || '').trim() || undefined,
    accountId: (env.REGISTRY_BROKER_ACCOUNT_ID || '').trim() || undefined,
  };
}

export function createRegistryBrokerClient(config = buildSidecarConfig()) {
  const options = { baseUrl: config.baseUrl };
  if (config.apiKey) {
    options.apiKey = config.apiKey;
  }
  if (config.accountId) {
    options.accountId = config.accountId;
  }
  return new RegistryBrokerClient(options);
}

function extractSdkErrorDetail(error) {
  const body = error?.body;
  if (body && typeof body === 'object') {
    const detail = firstString([body.detail, body.error, body.message]);
    if (detail) {
      const creditKeys = ['requiredCredits', 'availableCredits', 'shortfallCredits'];
      const creditParts = creditKeys
        .filter((key) => Object.prototype.hasOwnProperty.call(body, key))
        .map((key) => `${key}=${body[key]}`);
      return creditParts.length > 0 ? `${detail} (${creditParts.join(', ')})` : detail;
    }
    return JSON.stringify(body);
  }

  const response = error?.response;
  if (response && typeof response === 'object') {
    const detail = firstString([
      response.detail,
      response.error,
      response.message,
      response.statusText,
    ]);
    if (detail) {
      return detail;
    }
  }

  return firstString([error?.message, `${error}`]) || 'Unknown HOL SDK error';
}

function sdkErrorStatus(error) {
  const candidates = [
    error?.status,
    error?.statusCode,
    error?.response?.status,
    error?.cause?.status,
  ];
  for (const value of candidates) {
    const parsed = Number(value);
    if (Number.isFinite(parsed) && parsed >= 100 && parsed <= 599) {
      return parsed;
    }
  }
  return 500;
}

function normalizeHistorySnapshot(snapshot) {
  if (Array.isArray(snapshot)) {
    return { messages: snapshot };
  }
  if (!snapshot || typeof snapshot !== 'object') {
    return { messages: [] };
  }
  if (Array.isArray(snapshot.messages)) {
    return { messages: snapshot.messages };
  }
  if (Array.isArray(snapshot.history)) {
    return { messages: snapshot.history };
  }
  return { messages: [] };
}

function clamp(value, min, max, fallback) {
  const parsed = Number.parseInt(`${value ?? fallback}`, 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(min, Math.min(max, parsed));
}

export function createHolSidecarHandler({
  env = process.env,
  clientFactory = createRegistryBrokerClient,
} = {}) {
  const config = buildSidecarConfig(env);

  return async function holSidecarHandler(req, res) {
    const url = new URL(req.url || '/', `http://${req.headers.host || '127.0.0.1'}`);

    try {
      if (req.method === 'GET' && url.pathname === '/health') {
        jsonResponse(res, 200, {
          ok: true,
          baseUrl: config.baseUrl,
          hasApiKey: Boolean(config.apiKey),
        });
        return;
      }

      const client = clientFactory(config);

      if (req.method === 'POST' && url.pathname === '/search') {
        const body = await readJsonBody(req);
        const query = firstString([body.query, body.q]);
        if (!query) {
          jsonResponse(res, 400, { detail: 'query is required' });
          return;
        }
        const filters =
          body.filters && typeof body.filters === 'object' && !Array.isArray(body.filters)
            ? body.filters
            : {};
        const payload = {
          q: query,
          limit: clamp(body.limit, 1, 100, 5),
          ...filters,
        };
        const result = await client.search(payload);
        jsonResponse(res, 200, result);
        return;
      }

      if (req.method === 'POST' && url.pathname === '/register') {
        const body = await readJsonBody(req);
        const agentPayload =
          body.agent_payload && typeof body.agent_payload === 'object' && !Array.isArray(body.agent_payload)
            ? body.agent_payload
            : null;
        const mode = firstString([body.mode]) || 'register';
        if (!agentPayload) {
          jsonResponse(res, 400, { detail: 'agent_payload is required' });
          return;
        }
        if (mode !== 'register' && mode !== 'quote') {
          jsonResponse(res, 400, { detail: "mode must be either 'quote' or 'register'" });
          return;
        }
        const result =
          mode === 'quote'
            ? await client.getRegistrationQuote(agentPayload)
            : await client.registerAgent(agentPayload);
        jsonResponse(res, 200, result);
        return;
      }

      if (req.method === 'POST' && url.pathname === '/chat/session') {
        const body = await readJsonBody(req);
        const uaid = firstString([body.uaid]);
        const agentUrl = firstString([body.agent_url, body.agentUrl]);
        if (!uaid && !agentUrl) {
          jsonResponse(res, 400, { detail: 'uaid or agent_url is required' });
          return;
        }
        const payload = {
          ...(uaid ? { uaid } : { agentUrl }),
          ...(body.as_uaid ? { senderUaid: body.as_uaid } : {}),
          ...(body.history_ttl_seconds ? { historyTtlSeconds: body.history_ttl_seconds } : {}),
        };
        if (body.transport) {
          payload.transport = body.transport;
        }
        const result = await client.createSession(payload);
        jsonResponse(res, 200, result);
        return;
      }

      if (req.method === 'POST' && url.pathname === '/chat/message') {
        const body = await readJsonBody(req);
        const message = firstString([body.message]);
        if (!message) {
          jsonResponse(res, 400, { detail: 'message is required' });
          return;
        }
        const sessionId = firstString([body.session_id, body.sessionId]);
        const uaid = firstString([body.uaid]);
        const agentUrl = firstString([body.agent_url, body.agentUrl]);
        if (!sessionId && !uaid && !agentUrl) {
          jsonResponse(res, 400, { detail: 'session_id, uaid, or agent_url is required' });
          return;
        }
        const payload = {
          message,
          ...(sessionId ? { sessionId } : {}),
          ...(uaid ? { uaid } : {}),
          ...(agentUrl ? { agentUrl } : {}),
          ...(body.streaming === true ? { streaming: true } : {}),
        };
        if (body.as_uaid) {
          payload.senderUaid = body.as_uaid;
        }
        const result = await client.sendMessage(payload);
        jsonResponse(res, 200, result);
        return;
      }

      if (req.method === 'GET' && url.pathname.startsWith('/chat/history/')) {
        const sessionId = decodeURIComponent(url.pathname.slice('/chat/history/'.length));
        if (!sessionId) {
          jsonResponse(res, 400, { detail: 'session_id is required' });
          return;
        }
        const snapshot = await client.fetchHistorySnapshot(sessionId, { decrypt: false });
        jsonResponse(res, 200, normalizeHistorySnapshot(snapshot));
        return;
      }

      jsonResponse(res, 404, { detail: 'Not found' });
    } catch (error) {
      jsonResponse(res, sdkErrorStatus(error), {
        detail: extractSdkErrorDetail(error),
        error_type: error?.name || 'Error',
      });
    }
  };
}

export function startHolSidecar(options = {}) {
  const config = buildSidecarConfig(options.env || process.env);
  const handler = createHolSidecarHandler(options);
  const server = createServer(handler);
  return new Promise((resolve) => {
    server.listen(options.port || config.port, options.host || config.host, () => resolve(server));
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const config = buildSidecarConfig(process.env);
  const server = await startHolSidecar({ env: process.env });
  const address = server.address();
  const host = typeof address === 'object' && address ? address.address : config.host;
  const port = typeof address === 'object' && address ? address.port : config.port;
  console.log(`HOL SDK sidecar listening on http://${host}:${port} -> ${config.baseUrl}`);
}
