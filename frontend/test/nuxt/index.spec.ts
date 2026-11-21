import { mountSuspended } from "@nuxt/test-utils/runtime";
import { describe, expect, it } from "vitest";
import IndexPage from "../../app/pages/index.vue";

describe("index page", () => {
  it("links to the editor from the home page", async () => {
    const wrapper = await mountSuspended(IndexPage);

    expect(wrapper.get("h1").text()).toBe("Branchpoint");
    expect(wrapper.get('a[href="/editor"]').text()).toBe("Abrir editor");
  });
});
