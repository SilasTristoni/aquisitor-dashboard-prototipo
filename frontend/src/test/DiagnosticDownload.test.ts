import { afterEach, expect, test, vi } from "vitest";
import { download } from "../api";

afterEach(() => vi.unstubAllGlobals());

test("interrompe um corpo que excede o limite e não inicia download parcial", async () => {
  const cancel = vi.fn().mockResolvedValue(undefined);
  const reader = { read: vi.fn().mockResolvedValue({ done: false, value: new Uint8Array(16) }), cancel, releaseLock: vi.fn() };
  const createObjectURL = vi.fn();
  vi.stubGlobal("URL", { createObjectURL });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, body: { getReader: () => reader } }));
  await expect(download("/support/physical-package", "test.zip", { signal: new AbortController().signal, maxBytes: 8 })).rejects.toThrow("limite");
  expect(cancel).toHaveBeenCalled();
  expect(reader.releaseLock).toHaveBeenCalled();
  expect(createObjectURL).not.toHaveBeenCalled();
});

test("cancelamento também cobre o corpo e impede download tardio", async () => {
  const controller = new AbortController();
  const reader = { read: vi.fn().mockImplementation(() => {
    controller.abort(new Error("cancelled"));
    return Promise.resolve({ done: true });
  }), cancel: vi.fn().mockResolvedValue(undefined), releaseLock: vi.fn() };
  const createObjectURL = vi.fn();
  const fetch = vi.fn().mockResolvedValue({ ok: true, body: { getReader: () => reader } });
  vi.stubGlobal("URL", { createObjectURL });
  vi.stubGlobal("fetch", fetch);
  await expect(download("/support/physical-package", "test.zip", { signal: controller.signal, maxBytes: 8 })).rejects.toThrow("cancelled");
  expect(fetch.mock.calls[0][1].signal).toBe(controller.signal);
  expect(createObjectURL).not.toHaveBeenCalled();
});

test("propaga o erro acionável de tempo limite do backend", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 504, json: async () => ({ detail: "Utilize a coleta local." }) }));
  await expect(download("/support/physical-package", "test.zip")).rejects.toThrow("coleta local");
});
