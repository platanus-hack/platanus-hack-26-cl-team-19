import { mountSuspended } from "@nuxt/test-utils/runtime";
import { describe, expect, it } from "vitest";
import ChatChangeProposal from "../../app/components/editor/ChatChangeProposal.vue";
import type { ChatProposal } from "../../app/services/chat-stream";

function proposal(extra: Partial<ChatProposal> = {}): ChatProposal {
  return {
    id: "p",
    draft: { base: 1, scenario: { name: "cyberday" } },
    changes: ["Tráfico pico: 800 req/s."],
    warnings: [],
    ...extra,
  };
}

describe("tarjeta de propuesta de escenario (JAJ-149)", () => {
  it("distingue un escenario nuevo de un cambio de escenario", async () => {
    const created = await mountSuspended(ChatChangeProposal, {
      props: { proposal: proposal({ new_scenario: true }), state: "idle" },
    });
    expect(created.find("h3").text()).toBe("Nuevo escenario: CyberDay");
    expect(created.text()).not.toContain("desde v1");

    const changed = await mountSuspended(ChatChangeProposal, {
      props: { proposal: proposal(), state: "idle" },
    });
    expect(changed.find("h3").text()).toBe("Cambio de escenario: CyberDay");
    expect(changed.text()).toContain("desde v1");
  });

  it("al aceptar un escenario nuevo dice que se creó, sin versión", async () => {
    const card = await mountSuspended(ChatChangeProposal, {
      props: {
        proposal: proposal({ new_scenario: true }),
        state: "applied",
        version: "v1",
      },
    });
    expect(card.find('[role="status"]').text()).toBe("Escenario creado");
  });
});
