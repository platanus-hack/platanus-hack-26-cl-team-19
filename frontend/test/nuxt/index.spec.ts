import { mountSuspended } from "@nuxt/test-utils/runtime";
import { describe, expect, it } from "vitest";
import IndexPage from "../../app/pages/index.vue";

describe("index page", () => {
  it("links to projects from the home page", async () => {
    const wrapper = await mountSuspended(IndexPage);

    expect(wrapper.get("h1").text()).toBe("branchpoint");
    expect(wrapper.get('a[href="/projects"]').text()).toBe("Ver proyectos");
  });
});
