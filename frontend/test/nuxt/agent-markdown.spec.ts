import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import AgentMarkdown from "@/components/editor/AgentMarkdown.vue";

describe("Markdown del agente", () => {
  it("renderiza el formato de una respuesta guardada", () => {
    const response = [
      "## Resultado",
      "- Revisa `GET /orders`.",
      "- Abre la [guía](https://example.com/guide).",
      "",
      "1. Ejecuta la simulación.",
      "",
      "```sql",
      "SELECT * FROM orders;",
      "```",
    ].join("\n");
    const message = mount(AgentMarkdown, { props: { text: response } });

    expect(message.get("h2").text()).toBe("Resultado");
    expect(message.findAll("ul li")).toHaveLength(2);
    expect(message.get("ol li").text()).toBe("Ejecuta la simulación.");
    expect(message.get("li code").text()).toBe("GET /orders");
    expect(message.get("a").attributes("href")).toBe(
      "https://example.com/guide",
    );
    expect(message.get("pre code").text()).toBe("SELECT * FROM orders;");
  });

  it("actualiza el formato a medida que llega texto", async () => {
    const message = mount(AgentMarkdown, { props: { text: "## Resultado" } });

    expect(message.get("h2").text()).toBe("Resultado");
    await message.setProps({
      text: "## Resultado\n\n```ts\nconst replicas = 2;",
    });
    expect(message.get("pre code").text()).toBe("const replicas = 2;");
  });

  it("mantiene el HTML como texto y bloquea enlaces inseguros e imágenes", () => {
    const message = mount(AgentMarkdown, {
      props: {
        text: [
          '<img src="x" onerror="alert(1)">',
          "[Script](java&#x73;cript:alert%281%29)",
          "[Archivo](file:///tmp/test)",
          "[Datos](data:image/png;base64,AA)",
          "![Imagen externa](https://example.com/image.png)",
          "[Referencia](/docs)",
        ].join("\n\n"),
      },
    });

    expect(message.find("img").exists()).toBe(false);
    expect(message.text()).toContain('<img src="x" onerror="alert(1)">');
    const links = message.findAll("a").map((link) => link.attributes("href"));
    expect(links).not.toContain("javascript:alert%281%29");
    expect(links.every((href) => /^(https:\/\/|\/)/.test(href ?? ""))).toBe(
      true,
    );
    expect(links).toContain("/docs");
  });
});
