// Minimal canvas environment for exercising actual renderer drawing and disposal.
module.exports = function withCanvasEnvironment(run, color = (name) => name) {
	const values = {
		document: { documentElement: {} },
		getComputedStyle: () => ({ getPropertyValue: color }),
		ResizeObserver: class {
			observe() {}
			disconnect() {}
		},
	};
	const original = new Map(Object.keys(values).map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
	Object.assign(globalThis, values);
	try {
		return run();
	} finally {
		for (const [key, descriptor] of original) {
			if (descriptor) Object.defineProperty(globalThis, key, descriptor);
			else delete globalThis[key];
		}
	}
};
