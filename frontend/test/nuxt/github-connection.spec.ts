import { describe, expect, it } from "vitest";
import { githubErrorMessage } from "../../app/composables/useGithubConnection";

describe("mensajes de error de GitHub", () => {
  it("usa el mensaje del backend cuando viene", () => {
    const cause = { data: { error: { message: "La app no está instalada." } } };
    expect(githubErrorMessage(cause)).toBe("La app no está instalada.");
  });

  it("conserva los errores propios del cliente, como la sesión vencida", () => {
    const cause = new Error("Tu sesión expiró. Vuelve a iniciar sesión.");
    expect(githubErrorMessage(cause)).toBe(
      "Tu sesión expiró. Vuelve a iniciar sesión.",
    );
  });

  it("no muestra el texto técnico de un fetch fallido", () => {
    const cause = Object.assign(
      new Error("[GET] /github/repos: <no response>"),
      {
        name: "FetchError",
      },
    );
    expect(githubErrorMessage(cause)).toMatch(/backend esté activo/);
  });
});
