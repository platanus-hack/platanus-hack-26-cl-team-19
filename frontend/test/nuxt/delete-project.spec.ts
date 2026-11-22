import { mountSuspended } from "@nuxt/test-utils/runtime";
import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";
import DeleteProjectDialog from "../../app/components/projects/DeleteProjectDialog.vue";
import { createMockEditorApi } from "../../app/services/editor-mock";

function button(name: string) {
  return [...document.body.querySelectorAll("button")].find((element) =>
    element.textContent?.includes(name),
  );
}

describe("borrar un proyecto", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("el editor de demostración deja de listar el proyecto borrado", async () => {
    const api = createMockEditorApi();
    const { id } = await api.createProject("full-stack-fastapi-template");

    await api.deleteProject(id);

    const projects = await api.listProjects();
    expect(projects.map((project) => project.id)).not.toContain(id);
    await expect(api.getProject(id)).rejects.toThrow();
  });

  it("pide confirmación y avisa cuando se borró", async () => {
    const { api } = useProjectApi();
    const project = await api.createProject("full-stack-fastapi-template");
    project.name = "Tienda";
    const wrapper = await mountSuspended(DeleteProjectDialog, {
      props: { project },
      attachTo: document.body,
    });

    expect(document.body.textContent).toContain("¿Borrar «Tienda»?");
    expect(document.body.textContent).toContain("No se puede deshacer");

    button("Borrar proyecto")!.click();
    await flushPromises();

    expect(wrapper.emitted("deleted")).toEqual([[project.id]]);
    const projects = await api.listProjects();
    expect(projects.map(({ id }) => id)).not.toContain(project.id);
  });

  it("cancelar cierra sin borrar", async () => {
    const { api } = useProjectApi();
    const project = await api.createProject("full-stack-fastapi-template");
    const wrapper = await mountSuspended(DeleteProjectDialog, {
      props: { project },
      attachTo: document.body,
    });

    button("Cancelar")!.click();
    await flushPromises();

    expect(wrapper.emitted("close")).toHaveLength(1);
    expect(wrapper.emitted("deleted")).toBeUndefined();
    await expect(api.getProject(project.id)).resolves.toBeTruthy();
  });
});
