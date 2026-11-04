export type Preference = 'Auto' | 'Light' | 'Dark';
const choices: Preference[] = ['Auto', 'Light', 'Dark'];
export function createTheme(storage: Pick<Storage, 'getItem' | 'setItem'>, media: MediaQueryList, root: HTMLElement) {
	let preference: Preference = 'Auto';
	try {
		const saved = storage.getItem('spot-theme');
		if (choices.includes(saved as Preference)) preference = saved as Preference;
	} catch {}
	const listeners = new Set<() => void>();
	const apply = () => {
		root.dataset.theme = preference === 'Auto' ? (media.matches ? 'dark' : 'light') : preference.toLowerCase();
		root.dataset.preference = preference;
		for (const fn of listeners) fn();
	};
	media.addEventListener('change', apply);
	apply();
	return {
		get: () => preference,
		subscribe: (fn: () => void) => {
			listeners.add(fn);
			return () => {
				listeners.delete(fn);
			};
		},
		set: (value: Preference) => {
			preference = value;
			try {
				storage.setItem('spot-theme', value);
			} catch {}
			apply();
		},
	};
}
