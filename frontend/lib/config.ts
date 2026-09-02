function trimTrailingSlash(value: string) {
  return value.replace(/\/+$/, "");
}

function deriveWebSocketBaseUrl(httpUrl: string) {
  if (httpUrl.startsWith("https://")) {
    return `wss://${httpUrl.slice("https://".length)}`;
  }
  if (httpUrl.startsWith("http://")) {
    return `ws://${httpUrl.slice("http://".length)}`;
  }
  return httpUrl;
}

const resolvedApiBaseUrl = trimTrailingSlash(
  process.env.NEXT_PUBLIC_API_BASE_URL || process.env.API_BASE_URL || "http://localhost:8010",
);

export const apiBaseUrl = resolvedApiBaseUrl;
export const publicAppUrl = trimTrailingSlash(
  process.env.NEXT_PUBLIC_APP_URL || process.env.PUBLIC_APP_URL || "http://localhost:3000",
);

export const wsBaseUrl = trimTrailingSlash(
  process.env.NEXT_PUBLIC_WS_BASE_URL || deriveWebSocketBaseUrl(resolvedApiBaseUrl),
);
