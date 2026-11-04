(() => {
	'use strict';
	let preference = 'Auto';
	try {
		preference = localStorage.getItem('spot-theme') || 'Auto';
	} catch {}
	if (!['Auto', 'Light', 'Dark'].includes(preference)) preference = 'Auto';
	const os = matchMedia('(prefers-color-scheme: dark)');
	const apply = () => {
		document.documentElement.dataset.theme =
			preference === 'Auto' ? (os.matches ? 'dark' : 'light') : preference.toLowerCase();
		document.documentElement.dataset.preference = preference;
		dispatchEvent(new CustomEvent('spot-theme', { detail: preference }));
	};
	window.SpotTheme = {
		get: () => preference,
		set: (value) => {
			if (!['Auto', 'Light', 'Dark'].includes(value)) return;
			preference = value;
			try {
				localStorage.setItem('spot-theme', value);
			} catch {}
			apply();
		},
	};
	os.addEventListener('change', apply);
	apply();
})();
