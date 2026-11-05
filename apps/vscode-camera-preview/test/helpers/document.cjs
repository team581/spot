// Minimal DOM for building the shared renderer's scene (labels are DOM elements) without WebGL.
module.exports = function withDocument(run) {
	const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'document');
	globalThis.document = {
		createElement: () => ({ style: {}, textContent: '', setAttribute() {}, remove() {} }),
	};
	try {
		return run();
	} finally {
		if (descriptor) Object.defineProperty(globalThis, 'document', descriptor);
		else delete globalThis.document;
	}
};
