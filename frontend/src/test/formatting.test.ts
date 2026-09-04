import { describe, expect, test } from "vitest";
import { formatDate, formatDuration, friendlyApiMessage, parseApiDate } from "../api";
import { formatElapsedAxis } from "../utils/chartPresentation";

describe("formatação para operação", () => {
  test("apresenta durações em linguagem natural", () => {
    expect(formatDuration(45)).toBe("45 s");
    expect(formatDuration(750)).toBe("12 min 30 s");
    expect(formatDuration(4680)).toBe("1 h 18 min");
    expect(formatDuration(86_400)).toBe("24 h");
  });

  test("mantém o eixo comparativo no formato técnico de tempo decorrido", () => {
    expect(formatElapsedAxis(0)).toBe("00:00:00");
    expect(formatElapsedAxis(3723)).toBe("01:02:03");
  });

  test("traduz códigos conhecidos sem esconder mensagens úteis", () => {
    expect(friendlyApiMessage("protocol_timeout")).toBe(
      "O equipamento não respondeu dentro do tempo esperado.",
    );
    expect(friendlyApiMessage("Cabo desconectado")).toBe("Cabo desconectado");
  });
});

describe("datas UTC recebidas da API", () => {
  test("interpreta timestamps sem sufixo como UTC, como ocorre no SQLite", () => {
    expect(parseApiDate("2026-09-04T12:37:00").toISOString()).toBe(
      "2026-09-04T12:37:00.000Z",
    );
    expect(formatDate("2026-09-04T12:37:00")).toContain("09:37:00");
  });
});
