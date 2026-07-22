import "@testing-library/jest-dom/vitest";

class ResizeObserverMock implements ResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

globalThis.ResizeObserver = ResizeObserverMock;

const storage = new Map<string, string>();
const localStorageMock: Storage = {
  get length() { return storage.size; },
  clear: () => storage.clear(),
  getItem: (key) => storage.get(key) ?? null,
  key: (index) => [...storage.keys()][index] ?? null,
  removeItem: (key) => { storage.delete(key); },
  setItem: (key, value) => { storage.set(key, String(value)); },
};

Object.defineProperty(window, "localStorage", { configurable: true, value: localStorageMock });

Object.defineProperty(HTMLElement.prototype, "getBoundingClientRect", {
  configurable: true,
  value: () => ({
    x: 0,
    y: 0,
    width: 800,
    height: 320,
    top: 0,
    right: 800,
    bottom: 320,
    left: 0,
    toJSON: () => ({}),
  }),
});
