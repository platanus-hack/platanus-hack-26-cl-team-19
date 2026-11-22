import { mountSuspended } from "@nuxt/test-utils/runtime";
import { describe, expect, it } from "vitest";
import { nextTick } from "vue";
import ProjectScenarioForm from "@/components/editor/ProjectScenarioForm.vue";
import SimulationPanel from "@/components/editor/SimulationPanel.vue";
import { createMockEditorApi } from "@/services/editor-mock";
import { simulationProvenance, toPlayback } from "@/services/editor-view";
import type { ProjectScenarioInput } from "@/services/editor-api";

describe("escenario elástico", () => {
  it("guarda y vuelve a abrir los parámetros del salto", async () => {
    const props = { names: [], hasPeak: false, busy: false };
    const form = await mountSuspended(ProjectScenarioForm, { props });
    await form.get('input[id$="-name"]').setValue("salto");
    form
      .findComponent({ name: "SelectRoot" })
      .vm.$emit("update:modelValue", "elastic");
    await nextTick();
    await form.get('input[id$="-rate"]').setValue(100);
    await form.get('input[id$="-jump-at"]').setValue(30);
    await form.get("form").trigger("submit");

    const [name, input] = form.emitted("save")![0] as [
      string,
      ProjectScenarioInput,
    ];
    expect(name).toBe("salto");
    expect(input).toMatchObject({
      rps: 100,
      multiplier: null,
      traffic_step: { at_s: 30, multiplier: 10, duration_s: 60 },
    });

    const api = createMockEditorApi();
    const { id } = await api.createProject("full-stack-fastapi-template");
    await api.saveScenario(id, name, input);
    const saved = (await api.listScenarios(id)).find(
      (scenario) => scenario.name === name,
    );
    const reopened = await mountSuspended(ProjectScenarioForm, {
      props: { ...props, existing: saved },
    });
    expect(reopened.get('[id$="-mode"]').text()).toBe(
      "Elástico, con salto instantáneo",
    );
    expect(
      reopened.get<HTMLInputElement>('input[id$="-rate"]').element.value,
    ).toBe("100");
    expect(
      reopened.get<HTMLInputElement>('input[id$="-jump-at"]').element.value,
    ).toBe("30");
    expect(
      reopened.get<HTMLInputElement>('input[id$="-jump-multiplier"]').element
        .value,
    ).toBe("10");
    await reopened.get('input[id$="-jump-at"]').setValue(60);
    expect(reopened.get('button[type="submit"]').attributes()).toHaveProperty(
      "disabled",
    );
  });

  it("dibuja un salto vertical en el segundo 30 a partir de la tasa objetivo", async () => {
    const api = createMockEditorApi();
    const { id } = await api.createProject("full-stack-fastapi-template");
    await api.saveScenario(id, "salto", {
      rps: 100,
      multiplier: null,
      description: null,
      traffic_step: { at_s: 30, multiplier: 10, duration_s: 60 },
    });
    const run = await api.run(id, 1, "salto");
    const { frames, phases } = toPlayback(run);
    expect(frames.map(({ targetRps }) => targetRps)).toEqual([
      ...Array(30).fill(100),
      ...Array(30).fill(1000),
    ]);

    const panel = await mountSuspended(SimulationPanel, {
      props: {
        minute: 30,
        frames,
        phases,
        timeUnit: "second",
        provenance: simulationProvenance,
      },
    });
    expect(panel.text()).toContain("30 s");
    const chart = panel.get('[aria-label^="Tráfico objetivo"]');
    const path = chart.get("path").attributes("d");
    expect(path).toContain(`H ${(30 / 59) * 100} V `);
    expect(path).not.toContain("L ");
  });
});
