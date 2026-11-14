import { vi } from 'vite-plus/test';

// Scene labels only need an element to hold their text.
vi.stubGlobal('document', { createElement: () => ({ setAttribute() {}, style: {} }) });
