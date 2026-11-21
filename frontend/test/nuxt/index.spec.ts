import { mountSuspended } from "@nuxt/test-utils/runtime";
import { describe, expect, it } from "vitest";
import IndexPage from "../../app/pages/index.vue";

describe("index page", () => {
  it("renders the scaffold status", async () => {
    const wrapper = await mountSuspended(IndexPage);

    expect(wrapper.get("h1").text()).toBe("Frontend listo");
  });
});
