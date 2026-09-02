const pakistanDateTime = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
  timeZone: "Asia/Karachi",
});

/** A deterministic display format that renders identically on the server and browser. */
export function formatPakistanDateTime(value: string | Date) {
  return pakistanDateTime.format(new Date(value));
}
