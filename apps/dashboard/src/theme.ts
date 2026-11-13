import { createTheme } from './state/theme';
// Access to localStorage itself can throw in restricted browser contexts.
const storage = {
	getItem: (key: string) => localStorage.getItem(key),
	setItem: (key: string, value: string) => {
		localStorage.setItem(key, value);
	},
};
export const theme = createTheme(storage, matchMedia('(prefers-color-scheme: dark)'), document.documentElement);
