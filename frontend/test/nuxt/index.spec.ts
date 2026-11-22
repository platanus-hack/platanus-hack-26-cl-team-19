import { mountSuspended } from "@nuxt/test-utils/runtime";
import { describe, expect, it } from "vitest";
import IndexPage from "../../app/pages/index.vue";

describe("index page", () => {
  it("shows the public animation and keeps project access gated", async () => {
    const wrapper = await mountSuspended(IndexPage);

    expect(wrapper.get("h1").text()).toBe(
      "Simula cómo responde tu arquitectura.",
    );
    expect(wrapper.find('a[href="/projects"]').exists()).toBe(false);
    expect(wrapper.find("#editor-en-vivo").exists()).toBe(true);
    expect(wrapper.get("button[disabled]").text()).toBe("Probar editor");
  });
});
