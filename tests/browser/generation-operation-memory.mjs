import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const moduleSource = await readFile(
    new URL(
        "../../flickornas_standings/web/static/js/generation-operation-memory.js",
        import.meta.url,
    ),
    "utf8",
);
const {
    LAST_GENERATION_OPERATION_KEY,
    rememberGenerationOperation,
    shouldShowRecoveredOperation,
} = await import(
    `data:text/javascript;base64,${Buffer.from(moduleSource).toString("base64")}`
);

const values = new Map();
const storage = {
    getItem(key) {
        return values.get(key) ?? null;
    },
    setItem(key, value) {
        values.set(key, value);
    },
    removeItem(key) {
        values.delete(key);
    },
};
const running = {
    terminal: false,
    topic: "operation-topic",
    status_url: "/api/v1/generation/operations/active",
};

rememberGenerationOperation(storage, running);
assert.deepEqual(
    JSON.parse(storage.getItem(LAST_GENERATION_OPERATION_KEY)),
    {
        topic: running.topic,
        statusUrl: running.status_url,
    },
);
assert.equal(shouldShowRecoveredOperation(running), true);

const completed = { ...running, terminal: true, state: "completed" };
rememberGenerationOperation(storage, completed);
assert.equal(storage.getItem(LAST_GENERATION_OPERATION_KEY), null);
assert.equal(shouldShowRecoveredOperation(completed), false);

const failed = { ...running, terminal: true, state: "failed" };
rememberGenerationOperation(storage, failed);
assert.equal(storage.getItem(LAST_GENERATION_OPERATION_KEY), null);
assert.equal(shouldShowRecoveredOperation(failed), false);
