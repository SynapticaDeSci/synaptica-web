import assert from 'node:assert/strict';
import test from 'node:test';
import { Readable } from 'node:stream';
import { createHolSidecarHandler } from './hol-sidecar.mjs';

async function invokeHandler(handler, { method, url, body }) {
  const req = Readable.from(body ? [Buffer.from(JSON.stringify(body))] : []);
  req.method = method;
  req.url = url;
  req.headers = { host: '127.0.0.1' };

  let statusCode = 200;
  let headers = {};
  let responseBody = '';

  const result = new Promise((resolve) => {
    const res = {
      writeHead(code, nextHeaders) {
        statusCode = code;
        headers = nextHeaders || {};
      },
      end(chunk = '') {
        responseBody += chunk ? chunk.toString() : '';
        resolve({
          statusCode,
          headers,
          payload: responseBody ? JSON.parse(responseBody) : null,
        });
      },
    };

    Promise.resolve(handler(req, res)).catch((error) => {
      resolve({
        statusCode: 500,
        headers: {},
        payload: { detail: error.message },
      });
    });
  });

  return result;
}

function createTestHandler(clientFactory) {
  return createHolSidecarHandler({
    env: {
      REGISTRY_BROKER_API_URL: 'https://registry.hashgraphonline.com/api/v1',
      REGISTRY_BROKER_API_KEY: 'rbk_test',
    },
    clientFactory,
  });
}

test('health endpoint reports sidecar config', async () => {
  const handler = createTestHandler(() => ({}));
  const response = await invokeHandler(handler, { method: 'GET', url: '/health' });
  assert.equal(response.statusCode, 200);
  assert.equal(response.payload.ok, true);
  assert.equal(response.payload.hasApiKey, true);
});

test('search forwards query and filters to HOL SDK client', async () => {
  const handler = createTestHandler(() => ({
    async search(payload) {
      assert.equal(payload.q, 'data agent');
      assert.equal(payload.limit, 12);
      assert.equal(payload.online, true);
      return { hits: [{ uaid: 'uaid:aid:test', name: 'Test Agent' }] };
    },
  }));

  const response = await invokeHandler(handler, {
    method: 'POST',
    url: '/search',
    body: { query: 'data agent', limit: 12, filters: { online: true } },
  });
  assert.equal(response.statusCode, 200);
  assert.equal(response.payload.hits[0].uaid, 'uaid:aid:test');
});

test('search falls back to raw broker request on SDK parse error', async () => {
  let requestedPath = null;
  const handler = createTestHandler(() => ({
    async search() {
      const error = new Error('Failed to parse search response');
      error.name = 'RegistryBrokerParseError';
      throw error;
    },
    async requestJson(path, config) {
      requestedPath = [path, config.method];
      return { hits: [{ uaid: 'uaid:aid:raw', name: 'Raw Agent' }] };
    },
  }));

  const response = await invokeHandler(handler, {
    method: 'POST',
    url: '/search',
    body: { query: 'data agent', limit: 7, filters: { online: true } },
  });
  assert.equal(response.statusCode, 200);
  assert.equal(response.payload.hits[0].uaid, 'uaid:aid:raw');
  assert.equal(requestedPath[1], 'GET');
  assert.match(requestedPath[0], /^\/search\?/);
});

test('register quote uses SDK quote method', async () => {
  const handler = createTestHandler(() => ({
    async getRegistrationQuote(payload) {
      assert.equal(payload.profile.display_name, 'Demo Agent');
      assert.equal(payload.endpoint, 'https://agent.example.com/execute');
      assert.equal(payload.additionalRegistries.length, 0);
      return { requiredCredits: 10, availableCredits: 5 };
    },
    async registerAgent() {
      throw new Error('registerAgent should not be called for quote');
    },
  }));

  const response = await invokeHandler(handler, {
    method: 'POST',
    url: '/register',
    body: {
      mode: 'quote',
      agent_payload: {
        profile: { display_name: 'Demo Agent' },
        endpoint_url: 'https://agent.example.com/execute',
      },
    },
  });
  assert.equal(response.statusCode, 200);
  assert.equal(response.payload.requiredCredits, 10);
});

test('chat routes preserve transport and sender UAID', async () => {
  let capturedSessionPayload = null;
  let capturedMessagePayload = null;
  const handler = createTestHandler(() => ({
    async createSession(payload) {
      capturedSessionPayload = payload;
      return { sessionId: 'session-123', history: [] };
    },
    async sendMessage(payload) {
      capturedMessagePayload = payload;
      return { reply: 'ack' };
    },
    async fetchHistorySnapshot() {
      return { history: [{ role: 'assistant', content: 'ack' }] };
    },
  }));

  const sessionResponse = await invokeHandler(handler, {
    method: 'POST',
    url: '/chat/session',
    body: {
      uaid: 'uaid:aid:test',
      transport: 'http',
      as_uaid: 'uaid:aid:sender',
    },
  });
  assert.equal(sessionResponse.statusCode, 200);
  assert.equal(capturedSessionPayload.transport, 'http');
  assert.equal(capturedSessionPayload.senderUaid, 'uaid:aid:sender');

  const messageResponse = await invokeHandler(handler, {
    method: 'POST',
    url: '/chat/message',
    body: {
      session_id: 'session-123',
      message: 'hello',
      as_uaid: 'uaid:aid:sender',
    },
  });
  assert.equal(messageResponse.statusCode, 200);
  assert.equal(capturedMessagePayload.sessionId, 'session-123');
  assert.equal(capturedMessagePayload.senderUaid, 'uaid:aid:sender');
});
