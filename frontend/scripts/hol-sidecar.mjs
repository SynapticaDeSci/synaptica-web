import { createServer } from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { RegistryBrokerClient, RegistryBrokerParseError } from '@hashgraphonline/standards-sdk';

const DEFAULT_BASE_URL = 'https://hol.org/registry/api/v1';
const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 8040;
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, '..', '..');

function loadEnvFile(filePath, target = process.env) {
  if (!fs.existsSync(filePath)) {
    return;
  }

  const content = fs.readFileSync(filePath, 'utf8');
  for (const rawLine of content.split(/\r?\n/u)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) {
      continue;
    }
    const separatorIndex = line.indexOf('=');
    if (separatorIndex <= 0) {
      continue;
    }
    const key = line.slice(0, separatorIndex).trim();
    if (!key || Object.prototype.hasOwnProperty.call(target, key)) {
      continue;
    }
    let value = line.slice(separatorIndex + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    target[key] = value;
  }
}

loadEnvFile(path.join(REPO_ROOT, '.env'));

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

function isRegistryBrokerParseError(error) {
  return error instanceof RegistryBrokerParseError || error?.name === 'RegistryBrokerParseError';
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

function normalizeRegistrationPayload(agentPayload) {
  const normalized =
    agentPayload && typeof agentPayload === 'object' && !Array.isArray(agentPayload)
      ? { ...agentPayload }
      : {};

  const endpoint = firstString([normalized.endpoint, normalized.endpoint_url, normalized.endpointUrl]);
  const protocol = firstString([
    normalized.protocol,
    normalized.communicationProtocol,
    normalized.communication_protocol,
  ]);
  const registry = firstString([normalized.registry]);
  const additionalRegistries = Array.isArray(normalized.additionalRegistries)
    ? normalized.additionalRegistries.filter((value) => typeof value === 'string' && value.trim())
    : [];
  const metadata =
    normalized.metadata && typeof normalized.metadata === 'object' && !Array.isArray(normalized.metadata)
      ? { ...normalized.metadata }
      : {};

  if (!metadata.publicUrl && endpoint) {
    metadata.publicUrl = endpoint;
  }
  if (!metadata.nativeId && normalized.agent_id) {
    metadata.nativeId = normalized.agent_id;
  }

  const result = {
    profile:
      normalized.profile && typeof normalized.profile === 'object' && !Array.isArray(normalized.profile)
        ? normalized.profile
        : {},
    ...(endpoint ? { endpoint } : {}),
    ...(protocol ? { protocol } : {}),
    ...(protocol ? { communicationProtocol: protocol } : {}),
    ...(registry ? { registry } : {}),
    ...(additionalRegistries.length > 0 ? { additionalRegistries } : { additionalRegistries: [] }),
    ...(Object.keys(metadata).length > 0 ? { metadata } : {}),
  };

  return result;
}

async function requestRegisterRaw(client, sdkPayload, mode) {
  const path = mode === 'quote' ? '/register/quote' : '/register';
  return client.requestJson(path, {
    method: 'POST',
    body: sdkPayload,
    headers: { 'Content-Type': 'application/json' },
  });
}

async function requestSearchRaw(client, payload) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(payload || {})) {
    if (value === undefined || value === null) {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item !== undefined && item !== null) {
          query.append(key, `${item}`);
        }
      }
      continue;
    }
    if (typeof value === 'object') {
      query.append(key, JSON.stringify(value));
      continue;
    }
    query.append(key, `${value}`);
  }
  return client.requestJson(`/search?${query.toString()}`, {
    method: 'GET',
  });
}

async function requestCreateSessionRaw(client, payload) {
  return client.requestJson('/chat/session', {
    method: 'POST',
    body: payload,
    headers: { 'Content-Type': 'application/json' },
  });
}

async function requestSendMessageRaw(client, payload) {
  return client.requestJson('/chat/message', {
    method: 'POST',
    body: payload,
    headers: { 'Content-Type': 'application/json' },
  });
}

async function requestHistoryRaw(client, sessionId) {
  return client.requestJson(`/chat/history/${encodeURIComponent(sessionId)}`, {
    method: 'GET',
  });
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
        let result;
        try {
          result = await client.search(payload);
        } catch (error) {
          if (!isRegistryBrokerParseError(error)) {
            throw error;
          }
          result = await requestSearchRaw(client, payload);
        }
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
        const sdkPayload = normalizeRegistrationPayload(agentPayload);
        let result;
        try {
          result =
            mode === 'quote'
              ? await client.getRegistrationQuote(sdkPayload)
              : await client.registerAgent(sdkPayload);
        } catch (error) {
          if (!isRegistryBrokerParseError(error)) {
            throw error;
          }
          result = await requestRegisterRaw(client, sdkPayload, mode);
        }
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
        let result;
        try {
          result = await client.createSession(payload);
        } catch (error) {
          if (!isRegistryBrokerParseError(error)) {
            throw error;
          }
          result = await requestCreateSessionRaw(client, payload);
        }
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
        let result;
        try {
          result = await client.sendMessage(payload);
        } catch (error) {
          if (!isRegistryBrokerParseError(error)) {
            throw error;
          }
          result = await requestSendMessageRaw(client, payload);
        }
        jsonResponse(res, 200, result);
        return;
      }

      if (req.method === 'GET' && url.pathname.startsWith('/chat/history/')) {
        const sessionId = decodeURIComponent(url.pathname.slice('/chat/history/'.length));
        if (!sessionId) {
          jsonResponse(res, 400, { detail: 'session_id is required' });
          return;
        }
        let snapshot;
        try {
          snapshot = await client.fetchHistorySnapshot(sessionId, { decrypt: false });
        } catch (error) {
          if (!isRegistryBrokerParseError(error)) {
            throw error;
          }
          snapshot = await requestHistoryRaw(client, sessionId);
        }
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
