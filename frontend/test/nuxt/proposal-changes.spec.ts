import { describe, expect, it } from "vitest";
import { proposalChangeView } from "@/services/proposal-changes";

describe("cambios de una propuesta del chat", () => {
  it("el tráfico queda como etiqueta y valor, con coma decimal", () => {
    expect(proposalChangeView("Tráfico pico: 26.2 → 471.6 req/s.")).toEqual({
      kind: "row",
      label: "Tráfico pico",
      value: "26,2 → 471,6 req/s",
    });
  });

  it("la mezcla de endpoints queda como lista de endpoint y %", () => {
    const view = proposalChangeView(
      "Mezcla de endpoints del escenario: GET /workshops 40 %, GET /workshops/{workshop_id} 35 %, POST /bookings 10 % del tráfico (el resto, como en el modelo).",
    );
    expect(view).toMatchObject({
      kind: "list",
      label: "Mezcla de endpoints",
      items: [
        { name: "GET /workshops", value: "40 %" },
        { name: "GET /workshops/{workshop_id}", value: "35 %" },
        { name: "POST /bookings", value: "10 %" },
      ],
    });
  });

  it("dependencias y negocio también se separan", () => {
    expect(
      proposalChangeView(
        "Dependencias del escenario: stripe ×3, db ×1,5 el tiempo de sus pasos.",
      ),
    ).toMatchObject({
      items: [
        { name: "stripe", value: "×3" },
        { name: "db", value: "×1,5" },
      ],
    });
    expect(
      proposalChangeView(
        "Negocio del escenario: conversión 2.5 % y ticket US$40, para el costo de fallar.",
      ),
    ).toMatchObject({
      items: [
        { name: "conversión", value: "2,5 %" },
        { name: "ticket", value: "US$40" },
      ],
    });
  });

  it("una frase que no calza se muestra tal cual", () => {
    expect(proposalChangeView("Agrega una réplica a la API")).toEqual({
      kind: "text",
      text: "Agrega una réplica a la API",
    });
  });
});
