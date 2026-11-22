import { mountSuspended } from "@nuxt/test-utils/runtime";
import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import ProjectDiagramThumbnail from "../../app/components/projects/ProjectDiagramThumbnail.vue";
import {
  createMockEditorApi,
  DEMO_PROJECT_ID,
} from "../../app/services/editor-mock";

function observeVisibility() {
  let notify: (() => void) | undefined;
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();

      constructor(callback: IntersectionObserverCallback) {
        notify = () =>
          callback(
            [{ isIntersecting: true } as IntersectionObserverEntry],
            this as unknown as IntersectionObserver,
          );
      }
    },
  );
  return () => notify?.();
}

function mockApi() {
  const api = createMockEditorApi(undefined, { landing: true });
  return {
    getVersion: vi.fn(api.getVersion),
    getGraph: vi.fn(api.getGraph),
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("miniatura de proyecto", () => {
  it("carga el diagrama de la versión solicitada al acercarse a la pantalla", async () => {
    const show = observeVisibility();
    const api = mockApi();
    const wrapper = await mountSuspended(ProjectDiagramThumbnail, {
      props: { projectId: DEMO_PROJECT_ID, version: 2, api },
    });

    expect(api.getVersion).not.toHaveBeenCalled();
    expect(api.getGraph).not.toHaveBeenCalled();

    show();
    await flushPromises();

    expect(api.getVersion).toHaveBeenCalledExactlyOnceWith(DEMO_PROJECT_ID, 2);
    expect(api.getGraph).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain("Worker");
    expect(wrapper.find("button, [role='toolbar']").exists()).toBe(false);

    await wrapper.setProps({ version: 1 });
    await flushPromises();

    expect(api.getVersion).toHaveBeenLastCalledWith(DEMO_PROJECT_ID, 1);
    expect(wrapper.text()).not.toContain("Worker");
    wrapper.unmount();
  });

  it("muestra un placeholder sin consultar un proyecto sin versiones", async () => {
    const show = observeVisibility();
    const api = mockApi();
    const wrapper = await mountSuspended(ProjectDiagramThumbnail, {
      props: { projectId: DEMO_PROJECT_ID, api },
    });

    show();
    await flushPromises();

    expect(wrapper.text()).toBe("Sin diagrama");
    expect(api.getVersion).not.toHaveBeenCalled();
    expect(api.getGraph).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("muestra un placeholder cuando falla la carga del diagrama", async () => {
    const show = observeVisibility();
    const api = mockApi();
    api.getGraph.mockRejectedValueOnce(new Error("Graph unavailable"));
    const wrapper = await mountSuspended(ProjectDiagramThumbnail, {
      props: { projectId: DEMO_PROJECT_ID, version: 1, api },
    });

    show();
    await flushPromises();

    expect(wrapper.text()).toBe("Miniatura no disponible");
    wrapper.unmount();
  });
});
