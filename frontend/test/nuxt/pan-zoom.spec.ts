import { describe, expect, it } from "vitest";
import {
  MAX_ZOOM,
  MIN_ZOOM,
  usePanZoom,
} from "../../app/composables/usePanZoom";

const viewport = { width: 800, height: 400 };
const content = { width: 400, height: 200 };

function pointer(x: number, y: number) {
  return { button: 0, clientX: x, clientY: y, pointerId: 1 } as PointerEvent;
}

describe("usePanZoom", () => {
  it("centra el diagrama completo al inicio", () => {
    const canvas = usePanZoom(viewport, content);
    expect(canvas.scale.value).toBe(1);
    expect(canvas.translate.value).toEqual({ x: 200, y: 100 });
  });

  it("amplía dejando fijo el punto bajo el cursor", () => {
    const canvas = usePanZoom(viewport, content);
    const at = { x: 300, y: 150 };
    const before = canvas.translate.value;
    const contentPoint = {
      x: (at.x - before.x) / canvas.scale.value,
      y: (at.y - before.y) / canvas.scale.value,
    };
    canvas.zoomTo(2, at);
    const after = canvas.translate.value;
    expect(after.x + contentPoint.x * canvas.scale.value).toBeCloseTo(at.x);
    expect(after.y + contentPoint.y * canvas.scale.value).toBeCloseTo(at.y);
  });

  it("limita el zoom", () => {
    const canvas = usePanZoom(viewport, content);
    canvas.zoomTo(100);
    expect(canvas.zoom.value).toBe(MAX_ZOOM);
    expect(canvas.canZoomIn.value).toBe(false);
    canvas.zoomTo(0.001);
    expect(canvas.zoom.value).toBe(MIN_ZOOM);
    expect(canvas.canZoomOut.value).toBe(false);
  });

  it("mueve el lienzo al arrastrar y no cuenta el arrastre como clic", () => {
    const canvas = usePanZoom(viewport, content);
    canvas.onPointerDown(pointer(10, 10));
    canvas.onPointerMove(pointer(60, 30));
    canvas.onPointerUp();
    expect(canvas.pan.value).toEqual({ x: 50, y: 20 });
    expect(canvas.consumeDrag()).toBe(true);
    expect(canvas.consumeDrag()).toBe(false);
  });

  it("un movimiento mínimo sigue siendo clic", () => {
    const canvas = usePanZoom(viewport, content);
    canvas.onPointerDown(pointer(10, 10));
    canvas.onPointerMove(pointer(11, 11));
    canvas.onPointerUp();
    expect(canvas.pan.value).toEqual({ x: 0, y: 0 });
    expect(canvas.consumeDrag()).toBe(false);
  });

  it("vuelve a la vista ajustada", () => {
    const canvas = usePanZoom(viewport, content);
    canvas.zoomIn();
    expect(canvas.isReset.value).toBe(false);
    canvas.reset();
    expect(canvas.isReset.value).toBe(true);
    expect(canvas.translate.value).toEqual({ x: 200, y: 100 });
  });
});
