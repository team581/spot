/** Fixed-point text for nullable numbers. */
export const fmt = (value: number | null | undefined, digits = 1) =>
	value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);

export const stateLabel = (state: string) => (state[0]?.toUpperCase() + state.slice(1)).replaceAll('_', ' ');

/** A commit's date in the viewer's time zone, as `YYYY-MM-DD`. */
export const commitDate = (unixSeconds: number) => new Date(unixSeconds * 1000).toLocaleDateString('en-CA');
