import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

globalThis.location = { origin: "http://flickornas.localhost:5000" };

const moduleSource = await readFile(
    new URL(
        "../../flickornas_standings/web/static/js/operation-stream.js",
        import.meta.url,
    ),
    "utf8",
);
const { followOperation } = await import(
    `data:text/javascript;base64,${Buffer.from(moduleSource).toString("base64")}`
);

class FakeEventSource {
    constructor(url) {
        this.url = url;
        this.listeners = new Map();
        this.closed = false;
    }

    addEventListener(kind, listener) {
        this.listeners.set(kind, listener);
    }

    dispatch(kind, event = {}) {
        this.listeners.get(kind)(event);
    }

    close() {
        this.closed = true;
    }
}

function response(operation) {
    return {
        ok: true,
        json: async () => ({ data: operation }),
    };
}

let source;
const operations = [];
const statusErrors = [];
const queuedStatuses = [
    { operation_id: "abc", latest_event_id: 2, state: "running" },
    { operation_id: "abc", latest_event_id: 4, state: "running" },
    { operation_id: "abc", latest_event_id: 5, state: "completed" },
];
let statusRequests = 0;
let pollingCallback;
let clearedTimer;
const follower = followOperation({
    hubUrl: "/.well-known/mercure",
    topic: "https://stockholmsschack.se/flickornas/operations/abc",
    statusUrl: "/api/v1/generation/operations/abc",
    onOperation(operation) {
        operations.push(operation);
    },
    onStatusError(error) {
        statusErrors.push(error);
    },
    eventSourceFactory(url) {
        source = new FakeEventSource(url);
        return source;
    },
    async fetchStatus(url) {
        assert.equal(url, "/api/v1/generation/operations/abc");
        const operation = queuedStatuses[statusRequests];
        statusRequests += 1;
        if (operation === undefined) {
            return { ok: false, status: 503 };
        }
        return response(operation);
    },
    setIntervalFactory(callback, delay) {
        assert.equal(delay, 2000);
        pollingCallback = callback;
        return "polling-timer";
    },
    clearIntervalFactory(timer) {
        clearedTimer = timer;
    },
});

await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(
    source.url,
    "http://flickornas.localhost:5000/.well-known/mercure"
        + "?topic=https%3A%2F%2Fstockholmsschack.se%2Fflickornas%2Foperations%2Fabc",
);
assert.deepEqual(operations.map((item) => item.latest_event_id), [2]);

// Duplicate notifications do not refetch or render stale state.
source.dispatch("message", { lastEventId: "2" });
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(statusRequests, 1);

// A newer notification reconciles through the durable endpoint.
source.dispatch("message", { lastEventId: "3" });
await new Promise((resolve) => setTimeout(resolve, 0));
assert.deepEqual(operations.map((item) => item.latest_event_id), [2, 4]);

// Native EventSource reconnects with Last-Event-ID; open/error both reconcile.
source.dispatch("error");
await new Promise((resolve) => setTimeout(resolve, 0));
assert.deepEqual(operations.map((item) => item.latest_event_id), [2, 4, 5]);
assert.deepEqual(statusErrors, []);
assert.equal(follower.latestEventId(), 5);
assert.equal(typeof pollingCallback, "function");

// A failed status read preserves the last known operation for a later retry.
source.dispatch("open");
await new Promise((resolve) => setTimeout(resolve, 0));
assert.deepEqual(operations.map((item) => item.latest_event_id), [2, 4, 5]);
assert.equal(statusErrors.length, 1);

follower.close();
assert.equal(source.closed, true);
assert.equal(clearedTimer, "polling-timer");

// Durable polling reaches terminal state when Mercure delivers no messages.
const polledOperations = [];
const pollingStatuses = [
    { operation_id: "poll-only", latest_event_id: 1, state: "running" },
    { operation_id: "poll-only", latest_event_id: 2, state: "completed" },
];
let pollOnlyCallback;
const pollingFollower = followOperation({
    hubUrl: "/.well-known/mercure",
    topic: "https://stockholmsschack.se/flickornas/operations/poll-only",
    statusUrl: "/api/v1/generation/operations/poll-only",
    onOperation(operation) {
        polledOperations.push(operation);
    },
    eventSourceFactory() {
        return new FakeEventSource("poll-only");
    },
    async fetchStatus() {
        return response(pollingStatuses.shift());
    },
    setIntervalFactory(callback) {
        pollOnlyCallback = callback;
        return "poll-only-timer";
    },
    clearIntervalFactory() {},
});
await new Promise((resolve) => setTimeout(resolve, 0));
assert.deepEqual(polledOperations.map((item) => item.state), ["running"]);
pollOnlyCallback();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.deepEqual(
    polledOperations.map((item) => item.state),
    ["running", "completed"],
);
pollingFollower.close();
