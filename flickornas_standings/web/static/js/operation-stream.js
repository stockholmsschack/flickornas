function operationEventId(operation) {
    const eventId = Number(operation?.latest_event_id);
    return Number.isSafeInteger(eventId) ? eventId : 0;
}

/**
 * Fetch operation status when Mercure sends a notification.
 * Use the operation endpoint for current status.
 */
export function followOperation({
    hubUrl,
    topic,
    statusUrl,
    onOperation,
    onStatusError = () => {},
    eventSourceFactory = (url) => new EventSource(url),
    fetchStatus = (url) => fetch(url, { headers: { Accept: "application/json" } }),
    reconcileInterval = 2000,
    setIntervalFactory = (callback, delay) => setInterval(callback, delay),
    clearIntervalFactory = (timer) => clearInterval(timer),
}) {
    let latestEventId = 0;
    let closed = false;
    let reconciliation = null;
    let requestedReconciliation = false;

    async function reconcile() {
        if (closed) {
            return;
        }
        if (reconciliation !== null) {
            requestedReconciliation = true;
            return reconciliation;
        }
        reconciliation = (async () => {
            do {
                requestedReconciliation = false;
                try {
                    const response = await fetchStatus(statusUrl);
                    if (!response.ok) {
                        throw new Error(`Operation status returned ${response.status}`);
                    }
                    const payload = await response.json();
                    const operation = payload.data;
                    const eventId = operationEventId(operation);
                    if (!closed && eventId > latestEventId) {
                        latestEventId = eventId;
                        onOperation(operation);
                    }
                } catch (error) {
                    if (!closed) {
                        onStatusError(error);
                    }
                }
            } while (requestedReconciliation && !closed);
        })();
        try {
            await reconciliation;
        } finally {
            reconciliation = null;
        }
    }

    const hub = new URL(hubUrl, globalThis.location.origin);
    hub.searchParams.append("topic", topic);
    const eventSource = eventSourceFactory(hub.toString());
    eventSource.addEventListener("open", reconcile);
    eventSource.addEventListener("error", reconcile);
    eventSource.addEventListener("message", function handleUpdate(event) {
        const eventId = Number(event.lastEventId);
        if (!Number.isSafeInteger(eventId) || eventId > latestEventId) {
            void reconcile();
        }
    });
    const pollingTimer = reconcileInterval > 0
        ? setIntervalFactory(() => void reconcile(), reconcileInterval)
        : null;
    void reconcile();

    return {
        reconcile,
        close() {
            closed = true;
            if (pollingTimer !== null) {
                clearIntervalFactory(pollingTimer);
            }
            eventSource.close();
        },
        latestEventId() {
            return latestEventId;
        },
    };
}
