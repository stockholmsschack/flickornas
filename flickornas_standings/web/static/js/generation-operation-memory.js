export const LAST_GENERATION_OPERATION_KEY =
    "flickornas:generation-operation";

export function rememberGenerationOperation(storage, operation) {
    if (operation.terminal) {
        storage.removeItem(LAST_GENERATION_OPERATION_KEY);
        return;
    }
    storage.setItem(
        LAST_GENERATION_OPERATION_KEY,
        JSON.stringify({
            topic: operation.topic,
            statusUrl: operation.status_url,
        }),
    );
}

export function shouldShowRecoveredOperation(operation) {
    return !operation.terminal;
}
