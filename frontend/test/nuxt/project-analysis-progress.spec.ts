import { mountSuspended } from "@nuxt/test-utils/runtime";
import { describe, expect, it } from "vitest";
import ProjectAnalysisProgress from "../../app/components/projects/ProjectAnalysisProgress.vue";
import type { Ingestion } from "../../app/services/github-api";

describe("progreso del análisis de proyecto", () => {
  it("mueve el paso activo cuando cambia la etapa que devuelve el backend", async () => {
    const wrapper = await mountSuspended(ProjectAnalysisProgress, {
      props: { job: null, detail: "Revisando el acceso al repo…" },
    });

    expect(wrapper.get('[aria-current="step"]').text()).toBe(
      "Comprobar acceso a GitHub",
    );
    expect(wrapper.get(".wordmark").text()).toBe("b.");
    expect(wrapper.get(".wordmark span").classes()).toContain(
      "motion-safe:animate-pulse",
    );

    const job: Ingestion = {
      id: "job",
      repo_full_name: "equipo/app",
      branch: "main",
      status: "running",
      stage: "analisis",
      commit_sha: null,
      endpoints: null,
      project_id: null,
      version: null,
      error_message: null,
      llm_steps: 3,
    };
    await wrapper.setProps({ job, detail: "Analizando con IA · paso 3" });

    expect(wrapper.get('[aria-current="step"]').text()).toBe(
      "Analizar la arquitectura",
    );
    expect(wrapper.get('[role="status"]').text()).toContain("paso 3");

    await wrapper.setProps({ job: { ...job, stage: "preparacion" } });
    expect(wrapper.get('[aria-current="step"]').text()).toBe(
      "Guardar la primera versión",
    );
  });
});
